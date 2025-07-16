import time
import serial
import threading

class ArduinoController:
    # Define analog pin names for clarity (as sent by the Arduino sketch)
    PIN_JOYSTICK_X = "JOYSTICK_X"  # Left/right control (printed as "JOYSTICK_X:<value>")
    PIN_JOYSTICK_Y = "JOYSTICK_Y"  # Up/down control (printed as "JOYSTICK_Y:<value>")
    PIN_JOYSTICK_SW = "JOYSTICK_SW"  # Up/down control (printed as "JOYSTICK_SW:<value>")

    def __init__(self, gui=None, artisan_controller=None):	
        # Attached external controller (e.g., Atrisan_Controller)
        self.gui = gui
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
                            data_sender = self.identify_sender(raw)

                            if data_sender is None:
                                print(f"Unknown data format: {raw}")
                                continue
                            
                            if data_sender == "Joystick":  
                                data = self.parse_analog_pins(raw)
                                if data:
                                #print("Parsed data:", data)
                                    self.handle_joystick(data[self.PIN_JOYSTICK_X],
                                                        data[self.PIN_JOYSTICK_Y],
                                                        data[self.PIN_JOYSTICK_SW])
                            elif data_sender == "Keypad":
                                # Handle keypad data if needed
                                print(f"Keypad data received: {raw}")
                                self.handle_keypad(raw)
                            elif data_sender == "Remote":
                                # Handle remote control 
                                self.handle_remote(raw)
                        except Exception as e:
                            print("Error in run_loop:", e)
                # Use a shorter sleep to yield control rather than collecting stale data
                time.sleep(0.01)
        except KeyboardInterrupt:
            print("Exiting read loop.")

    def identify_sender(self, raw):
        # Identify the sender of the data based on the raw input format.
        if raw.startswith("JOYSTICK_"):
            return "Joystick"
        elif raw.startswith("Keypad"):
            return "Keypad"
        elif raw.startswith("Remote"):
            return "Remote"
        return None

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

        # Detect X-axis state changes
        if x_value > theshold_high:
            if self.x_joystick_state != 1:
                # high event on x-Axis triggered
                self.atrisan_controller.move_axis_continuous("X", 1)
                self.x_joystick_state = 1
        elif x_value < threshold_low:
            if self.x_joystick_state != -1:
                #low event ont x-Axis triggered
                self.atrisan_controller.move_axis_continuous("X", -1)
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
                self.atrisan_controller.move_axis_continuous("Y", -1)
                self.y_joystick_state = 1
        elif y_value < threshold_low:
            if self.y_joystick_state != -1:
                #low event ont y-Axis triggered
                self.atrisan_controller.move_axis_continuous("Y", 1)
                self.y_joystick_state = -1
        else:
            if not self.y_joystick_state == 0:
                #neutral event on y-Axis triggered
                self.atrisan_controller.stop_axis()
                self.y_joystick_state = 0

    def handle_keypad(self, raw):
        # Handle keypad input 
        key = raw.split()[1]
        if key == "2":
            self.atrisan_controller.move_axis_step("Y", 1)
        elif key == "8":
            self.atrisan_controller.move_axis_step("Y", -1)
        elif key == "4":
            self.atrisan_controller.move_axis_step("X", -1)
        elif key == "6":
            self.atrisan_controller.move_axis_step("X", 1)
        elif key == "5":
            self.atrisan_controller.stop_axis()
        elif key == "A":
            self.atrisan_controller.move_axis_step("Z", 1)
        elif key == "B":
            self.atrisan_controller.move_axis_step("Z", -1)
        else:
            print(f"Unhandled keypad key: {key}")
    
    def handle_remote(self, raw):
        # Handle remote control input
        hex_code = raw.split()[1]
        if hex_code == "BA45FF00": # On/Off button
            
            speed = self.atrisan_controller.speed
            step_width = self.atrisan_controller.step_width
            send_string = f"Speed {speed}mm/s; Step {step_width}mm"
            self.ser.write((send_string + '\n').encode())
            print(f'refreshing LCD with {send_string}')
        elif hex_code == "B946FF00": # + Vol
            self.atrisan_controller.move_axis_step("Y", 1)
        elif hex_code == "B847FF00": # Func/stop
            pass
        elif hex_code == "BB44FF00": # << button
            self.atrisan_controller.move_axis_step("X", -1)
        elif hex_code == "BF40FF00": # Play/pause button
            self.atrisan_controller.stop_axis()
        elif hex_code == "BC43FF00": # >> button
            self.atrisan_controller.move_axis_step("X", 1)
        elif hex_code == "F807FF00": # down button
            self.atrisan_controller.move_axis_step("Z", -1)
        elif hex_code == "EA15FF00": # - Vol
            self.atrisan_controller.move_axis_step("Y", -1)
        elif hex_code == "F609FF00": # up button
            self.atrisan_controller.move_axis_step("Z", 1)
        else:
            print(f"Unhandled remote command: {hex_code}")