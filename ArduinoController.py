import time
import serial
import threading

class ArduinoController:
    # Define analog pin names for clarity (as sent by the Arduino sketch)
    PIN_JOYSTICK_X = "JOYSTICK_X"  # Left/right control (printed as "JOYSTICK_X:<value>")
    PIN_JOYSTICK_Y = "JOYSTICK_Y"  # Up/down control (printed as "JOYSTICK_Y:<value>")
    PIN_JOYSTICK_SW = "JOYSTICK_SW"  # Up/down control (printed as "JOYSTICK_SW:<value>")

    def __init__(self, artisan_controller=None):	
        # Attached external controller (e.g., Atrisan_Controller)
        self.atrisan_controller = artisan_controller
        self.ser = None  # Serial connection
        self.x_joystick_state = 0 # Previous state for X axis
        self.y_joystick_state = 0  # Previous state for Y axis

    def connect(self, port="COM5", baudrate=9600):
        # Establish a connection with Arduino via USB (COM port)
        try:
            self.ser = serial.Serial(port, baudrate, timeout=1)
            # Allow the Arduino to reset and start cleanly.
            time.sleep(2)
            self.ser.flushInput()
            print(f"Connected to Arduino UNO R3 on {port} at {baudrate} baud.")
            thread = threading.Thread(target=self.run_loop, daemon=True)
            thread.start()           
        except Exception as e:
            print(f"Failed to connect to Arduino UNO R3 on {port}: {e}")

    def run_loop(self):
        # Loop that continuously reads from the Arduino and processes analog joystick data.
        print("Starting serial read loop. Press Ctrl+C to exit.")
        try:
            while True:
                if self.ser and self.ser.in_waiting:
                    # Drain all available lines
                    while self.ser.in_waiting:
                        try:
                            raw = self.ser.readline().decode('utf-8').strip()
                            data = self.parse_analog_pins(raw)
                            if data:
                                #print("Parsed data:", data)
                                self.handle_joystick(data[self.PIN_JOYSTICK_X],
                                                     data[self.PIN_JOYSTICK_Y],
                                                     data[self.PIN_JOYSTICK_SW])
                        except Exception as e:
                            print("Error in run_loop:", e)
                # Use a shorter sleep to yield control rather than collecting stale data
                time.sleep(0.01)
        except KeyboardInterrupt:
            print("Exiting read loop.")

    def parse_analog_pins(self, raw):
        # Expected format: "X:<value> Y:<value> SW:<value>"
        try:
            parts = raw.split()
            data = {}
            for part in parts:
                if ":" in part:
                    pin, value = part.split(":")
                    try:
                        data[pin] = int(value)
                    except ValueError:
                        print(f"Non-integer value encountered for {pin}")
                        return None
            
            #Check if all expected keys are present
            if not all(key in data for key in [self.PIN_JOYSTICK_X, self.PIN_JOYSTICK_Y, self.PIN_JOYSTICK_SW]):
                print("Missing expected keys in data:", data)
                return None
            # Return the read DATA as a dictionary
            return data

        except Exception as e:
            print("Failed to parse analog input:", e)
            return None

    def handle_joystick(self, x_value, y_value, sw_value=None):
    
        if not self.atrisan_controller:
            print("No Atrisan_Controller attached. Ignoring joystick input.")
            return

        # Define thresholds
        theshold_high = 1000
        threshold_low = 23
        speed=30

        # Detect X-axis state changes
        if x_value > theshold_high:
            if self.x_joystick_state != 1:
                # high event on x-Axis triggered
                self.atrisan_controller.move_axis_continuous("X", 1, speed)
                self.x_joystick_state = 1
        elif x_value < threshold_low:
            if self.x_joystick_state != -1:
                #low event ont x-Axis triggered
                self.atrisan_controller.move_axis_continuous("X", -1, speed)
                self.x_joystick_state = -1
        else:
            if not self.x_joystick_state == 0:
                #neutral event on x-Axis triggered
                self.atrisan_controller.stop_axis()
                self.x_joystick_state = 0

        # Detect Y-axis state changes
        if y_value > theshold_high:
            if self.y_joystick_state != 1:
                # high event on y-Axis triggered
                self.atrisan_controller.move_axis_continuous("Y", -1, speed)
                self.y_joystick_state = 1
        elif y_value < threshold_low:
            if self.y_joystick_state != -1:
                #low event ont y-Axis triggered
                self.atrisan_controller.move_axis_continuous("Y", 1, speed)
                self.y_joystick_state = -1
        else:
            if not self.y_joystick_state == 0:
                #neutral event on y-Axis triggered
                self.atrisan_controller.stop_axis()
                self.y_joystick_state = 0

    # def process_signal(self, signal):
    #     # Process the signal locally if needed.
    #     if self.atrisan_controller:
    #         self.atrisan_controller.handle_signal(signal)
    #     else:
    #         print("No Atrisan_Controller attached. Signal received:", signal)

    # def attach_controller(self, controller):
    #     self.atrisan_controller = controller
    #     print("Atrisan_Controller attached")