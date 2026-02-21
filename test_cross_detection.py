import cv2
import numpy as np

def get_intersection(line1, line2):
    """
    Calculates the intersection point of two infinite lines.
    Line 1 is defined by (x1, y1) and (x2, y2).
    Line 2 is defined by (x3, y3) and (x4, y4).
    """

    x1, y1, x2, y2 = line1
    x3, y3, x4, y4 = line2
    # 1. Calculate the denominator
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    
    # 2. Check for parallel lines (denominator is 0)
    if d == 0:
        return None, None # Or raise an exception, depending on your needs
        
    # 3. Pre-calculate the cross products to avoid repeating operations
    cross_12 = (x1 * y2 - y1 * x2)
    cross_34 = (x3 * y4 - y3 * x4)
    
    # 4. Calculate the intersection point
    x_inter = (cross_12 * (x3 - x4) - (x1 - x2) * cross_34) / d
    y_inter = (cross_12 * (y3 - y4) - (y1 - y2) * cross_34) / d
    
    return x_inter, y_inter

def detect_laser_cross_refined(image_path):
    # 1. Load the image
    img = cv2.imread(image_path)
    if img is None:
        print("Error: Could not load image.")
        return None
    
    output_img = img.copy()

    # 2. Convert to HSV color space
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 3. Create a strict mask for RED color
    # We use a high Saturation threshold (>100) to ignore the white glare completely
    # We use a high Value threshold (>100) to ignore dark red background noise
    lower_red_1 = np.array([0, 100, 100])
    upper_red_1 = np.array([10, 255, 255])
    mask1 = cv2.inRange(hsv, lower_red_1, upper_red_1)

    lower_red_2 = np.array([160, 100, 100])
    upper_red_2 = np.array([180, 255, 255])
    mask2 = cv2.inRange(hsv, lower_red_2, upper_red_2)

    red_mask = mask1 | mask2

    # 4. Clean up the mask to remove tiny specks of noise
    kernel = np.ones((3,3), np.uint8)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)

    # 5. Detect lines using Probabilistic Hough Transform
    # minLineLength=40 ensures we only care about long, distinct laser arms
    too_many_lines = True
    threshold = 200
    while too_many_lines:
        lines = cv2.HoughLinesP(
            red_mask, 
            rho=1, 
            theta=np.pi/180, 
            threshold=threshold, 
            minLineLength=50, 
            maxLineGap=200 # Bridge the massive white gap in the center
        )

        if lines is None:
            print("No cross arms detected.")
            return output_img

        if threshold > 600:
            print("Too many lines detected, even with high threshold. Consider adjusting parameters.")
            return output_img
        if len(lines) > 30:
            threshold += 10
        else:
            too_many_lines = False

    # 6. Group coordinates by orientation
    v_coords_x = []
    h_coords_y = []

    v_lines = []
    h_lines = []
    
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.abs(np.arctan2(y2 - y1, x2 - x1) * 180.0 / np.pi)

        # Is it a vertical arm? (Angle near 90 degrees)
        if 70 < angle < 110:
            v_coords_x.extend([x1, x2])
            v_lines.append((x1, y1, x2, y2))
            
            cv2.line(output_img, (x1, y1), (x2, y2), (255, 0, 0), 1)
        # Is it a horizontal arm? (Angle near 0 or 180 degrees)
        elif angle < 20 or angle > 160:
            h_coords_y.extend([y1, y2])
            h_lines.append((x1, y1, x2, y2))

            cv2.line(output_img, (x1, y1), (x2, y2), (255, 255, 0), 1)

    # 7. Calculate the Median Intersection as a first guess for the center (Median is more robust to outliers than mean)
    # The median naturally ignores outliers (like a false line detected on the glare edge)
    center_x_guess, center_y_guess = None, None
    
    if v_coords_x:
        center_x_guess = int(np.median(v_coords_x))
    else:
        print("No vertical lines detected.")
        return None
    if h_coords_y:
        center_y_guess = int(np.median(h_coords_y))
    else:
        print("No horizontal lines detected.")
        return None

    #8. Calculate all intersactions of vertical and horizontal lines that are close to the median guess (within 20 pixels), and use these to refine the center guess
    close_v_lines = [line for line in v_lines if abs(line[0] - center_x_guess) < 20 or abs(line[2] - center_x_guess) < 20]
    close_h_lines = [line for line in h_lines if abs(line[1] - center_y_guess) < 20 or abs(line[3] - center_y_guess) < 20]

    intersections_x = []
    intersections_y = []
    # for v_line in close_v_lines:
    #     for h_line in close_h_lines:
    #         x_inter,y_inter = get_intersection(v_line, h_line)
            
    #         intersections_x.append(x_inter)
    #         intersections_y.append(y_inter)


    #get the lines closest to the gap
    #get closes vertical lines
    for i, v_line in enumerate(close_v_lines):
        h_line = (0, center_y_guess, img.shape[1], center_y_guess) # A horizontal line through the center guess

        x_inter,y_inter = get_intersection(v_line, h_line)
        intersections_x.append([x_inter,i])
    
    sorted_x = sorted(intersections_x)
    gaps = [sorted_x[i+1][0] - sorted_x[i][0] for i in range(len(sorted_x)-1)]
    max_gap_index = np.argmax(gaps)

    v_line_1 = close_v_lines[sorted_x[max_gap_index][1]]
    v_line_2 = close_v_lines[sorted_x[max_gap_index + 1][1]]
    
    #get closes horizontal lines
    for i,h_line in enumerate(close_h_lines):
        v_line =(center_x_guess, 0, center_x_guess, img.shape[0]) # A vertical line through the center guess

        x_inter,y_inter = get_intersection(v_line, h_line)
        intersections_y.append([y_inter,i])
    sorted_y = sorted(intersections_y)
    gaps = [sorted_y[i+1][0] - sorted_y[i][0] for i in range(len(sorted_y)-1)]
    max_gap_index = np.argmax(gaps)
    
    h_line_1 = close_h_lines[sorted_y[max_gap_index][1]]
    h_line_2 = close_h_lines[sorted_y[max_gap_index + 1][1]]
    
    #find the intersections of the closest lines to get a refined center guess
    intersections_x = []
    intersections_y = []
    for v_line in [v_line_1, v_line_2]:
        for h_line in [h_line_1, h_line_2]:
            x_inter,y_inter = get_intersection(v_line, h_line)
            
            intersections_x.append(x_inter)
            intersections_y.append(y_inter)

    for line in [v_line_1, v_line_2, h_line_1, h_line_2]:
        x1, y1, x2, y2 = line
        cv2.line(output_img, (x1, y1), (x2, y2), (0, 0, 255), 2)

    # 9. Refine the center guess by taking the median of these intersections
    center_x_guess = int(np.mean(intersections_x))
    center_y_guess = int(np.mean(intersections_y))

    # # 9. Refine the center guess by taking the median of these intersections
    # if intersections_x and intersections_y:
    #     # center_x_guess = int(np.mean(intersections_x))
    #     # center_y_guess = int(np.mean(intersections_y))

    #     #find the gap in the intersections
    #     if len(intersections_x) > 1:
    #         sorted_x = sorted(intersections_x)
    #         gaps = [sorted_x[i+1] - sorted_x[i] for i in range(len(sorted_x)-1)]
    #         max_gap_index = np.argmax(gaps)
    #         # The gap should be between the two clusters of intersections around the true center
    #         if gaps[max_gap_index] > 3: # Only consider it a valid gap if it's larger than 3 pixels
    #             center_x_guess = int((sorted_x[max_gap_index] + sorted_x[max_gap_index + 1]) / 2)

    #     if len(intersections_y) > 1:
    #         sorted_y = sorted(intersections_y)
    #         gaps = [sorted_y[i+1] - sorted_y[i] for i in range(len(sorted_y)-1)]
    #         max_gap_index = np.argmax(gaps)
    #         if gaps[max_gap_index] > 3:
    #             center_y_guess = int((sorted_y[max_gap_index] + sorted_y[max_gap_index + 1]) / 2)

    # 10. Draw the final result
    if center_x_guess is not None and center_y_guess is not None:
        center = (center_x_guess, center_y_guess)
        
        
        # Draw a bright green crosshair over the calculated center
        # cv2.circle(output_img, center, 8, (0, 255, 0), -1)
        cv2.line(output_img, (center_x_guess - 30, center_y_guess), (center_x_guess + 30, center_y_guess), (0, 255, 0), 2)
        cv2.line(output_img, (center_x_guess, center_y_guess - 30), (center_x_guess, center_y_guess + 30), (0, 255, 0), 2)
        
        print(f"Precise cross center found at: {center}")

    return output_img

# --- Execution ---
result = detect_laser_cross_refined("image_with_cross.png")
cv2.imshow("Detected Cross", result)
cv2.waitKey(0)
cv2.destroyAllWindows()
