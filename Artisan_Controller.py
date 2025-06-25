import serial #pyserial is a library for serial communication
import socket
import threading
import time

class ArtisanController():
    def __init__(self, connection_type="usb", port=None, baudrate=115200, ip=None, tcp_port=None):
        """
        Initialize the Snapmaker controller.
        :param connection_type: "usb" or "tcp"
        :param port: USB port (e.g., 'COM3' or '/dev/ttyUSB0') if using USB.
        :param baudrate: Baud rate for USB communication.
        :param ip: IP address of Snapmaker if using TCP/IP.
        :param tcp_port: Port number for TCP/IP communication.
        """
        self.port=port
        self.baudrate=baudrate
        self.ip=ip
        self.tcp_port=tcp_port
        self.connection = None
        self.connection_type = connection_type
        self.is_moving = False
        self.last_response = None
        self.work_position = None   
        self.connected=False
        self._current_position = [0, 0, 0]
        self._last_log = ''

        # Initialize the execution thread and events
        self.execution_thread = None
        self.execution_running = threading.Event()
        self.execution_canceled = threading.Event()
        self.execution_running.clear()  # Initially not running

        # Add a process state variable
        self.process_state = "Not Started"  # Possible states: "Not Started", "Running", "Paused", "Canclecd"
        self.process_commands = []

        #callbacks that can be connected to from a receiving class
        self.position_changed_callback = None
        self.log_callback = None

    #set a watcher on the current_position property and define a callback on it
    @property
    def current_position(self):
        return self._current_position

    @current_position.setter
    def current_position(self, value):
        self._current_position = value
        if self.position_changed_callback:
            self.position_changed_callback(value)

    def set_position_changed_callback(self, callback):
        self.position_changed_callback = callback 

    @property
    def last_log(self):
        return self._last_log
    
    @last_log.setter
    def last_log(self, value):
        self._last_log = value
        if self.log_callback:
            self.log_callback(value)

    def set_log_callback(self, callback):
        self.log_callback = callback

    def connect(self):
        if self.connection_type == "usb" and self.port:
            try:
                self.connection = serial.Serial(self.port, self.baudrate, timeout=1)
                self.last_log=f"Connected to Artisan via USB on {self.port}"
            except serial.SerialException as e:
                self.last_log=f"Failed to connect to Artisan via USB at the Port {self.port}: {e}"
                return
        elif self.connection_type == "tcp" and self.ip and self.tcp_port:
            self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.connection.connect((self.ip, self.tcp_port))
            self.last_log=f"Connected to Artisan via TCP/IP at {self.ip}:{self.tcp_port}"
        else:
            raise ValueError("Could not connect with given Parameters")
        
        self.connected=True
        self.work_position = self.get_position()
        self.current_position=self.get_position()
        
        #once connected, constantly track the axis position
        def track_axis():
            try:
                while self.connected:
                    time.sleep(0.1)
                    self.send_command("M114")
                    self.send_command("M114")
                    response=self.get_response()
                    counter=0
                    while not 'X:' in response and counter <5:
                        time.sleep(0.1)
                        response= self.connection.readline().decode().strip()
                        counter+=1
                        if response == "ok" or response == '':
                            break
                        
                    if 'X:' in response:
                        self.last_response = response
                        # # Example response: "X:10.00 Y:20.00 Z:30.00 E:0.00 Count X: 1000 Y: 2000 Z: 3000"
                        position = []
                        for part in self.last_response.split()[0:3]:
                            position.append(float(part.split(":")[1]))
                        #print(f"Got the Position: {position}")
                        self.current_position=position
            except Exception as e:
                self.last_log = f"Error in tracking axis: {e}"
        tracking_thread = threading.Thread(target=track_axis)
        tracking_thread.daemon = True
        tracking_thread.start()

    def disconnect(self):
        if not self.is_connection_active():
            self.last_log = "No Connection to disconnect was found."
            return
        self.connected=False
        self.last_log = "Disconnecting from Artisan..."
        time.sleep(1.5)
        if self.connection_type == "usb":
            self.connection.close()
            self.last_log = f"Disconnected from Artisan via USB on {self.port}"
        elif self.connection_type == "tcp":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            self.last_log = f"Disconnected from Artisan via TCP/IP at {self.ip}:{self.tcp_port}"
        else:
            raise ValueError("Could not disconnect. Either no connection was established in the first place or something went wrong.")
        

    def send_command(self, command):
        """
        Send a G-code command to Snapmaker.
        :param command: G-code command as a string.
        """
        if not self.is_connection_active():
            self.last_log = "Error: Not Connected to Artisan!"
            return
        
        try:
            if self.connection_type == "usb":
                self.connection.write((command + '\n').encode())
                response= self.get_response()
                if response == "ok" or response == '':
                    pass
                else:
                    self.last_response = response
            else:  # TCP/IP
                self.connection.sendall((command + '\n').encode())
                self.last_response = self.connection.recv(1024).decode().strip()
            #print(f"Response: {self.last_response}")
        except Exception as e:
            self.last_log = f"Failed to send command: {e}"
    
    def get_response(self):
        """
        Get the last response from the Snapmaker.
        :return: Last response from the Snapmaker.
        """
        if not self.is_connection_active():
            self.last_log = "Error: Not Connected to Artisan!"
            return
        
        try:
            response=self.connection.readline().decode().strip()
            return response
        except Exception as e:
            self.last_log = f"Failed to get response: {e}"
            return None

    def move_axis_continuous(self, axis, direction, speed):
        """
        Move an axis continuously while the button is pressed.
        :param axis: Axis to move ('X', 'Y', or 'Z').
        :param speed: Speed of movement (positive or negative).
        """
        self.is_moving = True
        #limit speed for Z-Axis!
        if axis=="Z" and speed >30:
                speed=30

        def move():
            # Set to relative positioning
            self.send_command("G91")
            interval=0.1
            while self.is_moving:               

                # Move the axis
                self.send_command(f"G0 {axis}{direction*speed*interval} F{speed*60}")
                time.sleep(interval)  # Adjust interval for smoother movement

            # Switch back to absolute positioning
            self.send_command("G90")

        thread = threading.Thread(target=move)
        thread.start()
    
    def move_axis_step(self, axis, direction, distance, speed):
        """
        Move an axis by a certain distance.
        :param axis: Axis to move ('X', 'Y', or 'Z').
        :param distance: Distance to move.
        :param speed: Speed of movement.
        """
        # Set to relative positioning
        self.send_command("G91")

        #limit speed for Z-Axis!
        if axis=="Z" and speed >30:
                speed=30

        # Move the axis
        self.send_command(f"G0 {axis}{direction*distance} F{speed*60}")

        # Switch back to absolute positioning
        self.send_command("G90")

    
    def move_axis_to(self, mode, x, y, z, speed):
        """
        Move an axis to a specific position.
        :param axis: Axis to move ('X', 'Y', or 'Z').
        :param position: Position to move to.
        :param speed: Speed of movement.
        """
        if mode == "absolute":
            # Set to absolute positioning
            self.send_command("G90")
        elif mode == "relative":
            # Set to relative positioning
            self.send_command("G91")
        else:
            self.last_log = "Error: Invalid move mode. Must be 'absolute' or 'relative'."

        #limit speed for Z-Axis!
        if speed >30:
            speed=30

        # Move the axis
        self.send_command(f"G0 X{x} Y{y} Z{z} F{speed*60}")

        # Switch back to absolute positioning
        self.send_command("G90")
    
    def home_axis(self, axis):
        """
        Home an axis.
        :param axis: Axis to home ('X', 'Y', or 'Z').
        """
        self.send_command(f"G28 {axis}")
    
    def get_position(self):
        """
        Get the current position of all axis.
        :return: Current position of all axis.
        """
        self.send_command("M114") # get new position     
        try:
            position = []
            for part in self.last_response.split()[0:3]:
                position.append(float(part.split(":")[1]))
            #print(f"Got the Position: {position}")
            return position
        except Exception as e:
            self.last_log = f"Failed to get position: {e}"
            return None
        
        
    def set_work_position(self):
        """
        Set the work position (origin) of the machine.
        :param x: X-coordinate of the work position.
        :param y: Y-coordinate of the work position.
        :param z: Z-coordinate of the work position.
        """
        self.work_position = self.current_position

    def stop_axis(self):
        """
        Stop axis movement when the button is released.
        """
        self.is_moving = False


    def emergency_stop(self):
        """
        Perform an emergency stop to halt all movements.
        """
        self.send_command("M112")  # Emergency stop command
        self.is_moving = False
        self.last_log = "Emergency stop issued."

    def set_laser_crosshair(self, state):
        if state=="on":
            self.send_command("M2000 L13 P1")
        else:
            self.send_command("M2000 L13 P0")
    
    def set_enclosure_light(self, state):
        if state=="on":
            self.send_command("M2000 W1 P100")
        else:
            self.send_command("M2000 W1 P0")
    
    def set_enclosure_fan(self, state):
        if state=="on":
            self.send_command("M2000 W2 P100")
        else:
            self.send_command("M2000 W2 P0")

    def set_air_assist(self, state):
        if state=="on":
            self.send_command("M8")
        else:
            self.send_command("M9")

    def read_nc_file(self, file_path):
        """
        Read NC data (G-code) from a file.
        :param file_path: Path to the NC file.
        :return: List of G-code commands.
        """
        try:
            with open(file_path, 'r') as file:
                self.process_commands = [line.strip() for line in file if line.strip() and not line.startswith(';')]
            self.last_log = f"Successfully read NC file: {file_path}"
        except Exception as e:
            self.last_log = f"Failed to read NC file: {e}"
            return []

    def start_process(self):
        """
        Execute NC data (G-code) from a file.
        :param file_path: Path to the NC file.
        """
        
        if not self.process_commands:
            self.last_log = "No commands to execute."
            return

        def execute():
            try:
                self.process_state = "Running"  # Update state to Running
                for command in self.process_commands:
                    if self.execution_canceled.is_set():
                        self.last_log = "Execution canceled."
                        break

                    self.execution_running.wait()  # Wait if paused

                    self.send_command(command)
                    time.sleep(0.1)  # Add a small delay between commands
                else:
                    if not self.execution_canceled.is_set():
                        self.last_log = "Execution completed successfully."
                        self.process_state = "Not Started"  # Reset state after completion
            except Exception as e:
                self.last_log = f"Error during execution: {e}"
                self.process_state = "Not Started"  # Reset state on error
            finally:
                # Ensure the thread is properly cleaned up
                if self.execution_thread and self.execution_thread.is_alive():
                    self.execution_thread.join()
                self.execution_thread = None

        # Start execution in a separate thread
        if self.process_state == "Not Started" or self.process_state == "Canceled":
            self.last_log= "Start Processing..."
            self.execution_canceled.clear()
            self.execution_running.set()
            self.execution_thread = threading.Thread(target=execute)
            self.execution_thread.start()
        else:
            self.last_log = "Execution already in progress or paused. Please cancel or resume first."
            
        

    def pause_process(self):
        """
        Pause the execution of the NC file.
        """
        self.execution_running.clear()
        self.last_log = "Execution paused."
        self.process_state = "Paused" # Update state to Paused
        self.last_log = "Execution paused."

    def resume_process(self):
        """
        Resume the execution of the NC file.
        """
        self.execution_running.set()
        self.last_log = "Execution resumed."
        self.process_state = "Running"  # Update state to Running
        self.last_log = "Execution resumed."

    def cancel_process(self):
        """
        Cancel the execution of the NC file.
        """
        if self.process_state in ["Running", "Paused"]:  # Only allow canceling if running or paused
            self.execution_canceled.set()
            
            # Wait for the execution thread to finish
            if self.execution_thread and self.execution_thread.is_alive():
                self.execution_thread.join()  # Wait for the thread to finish
            self.last_log = "Execution canceled."

            # Reset the execution state
            self.process_state = "Canceled"

    def is_connection_active(self):
        #first check if there is even a connection of any type that could be active
        if not self.connection:
            return False
        
        if self.connection_type == "usb":
            return self.connection.is_open
        elif self.connection_type == "tcp":
            try:
                self.connection.send(b'')
                return True
            except (socket.error, AttributeError):
                return False
        else:
            return False


