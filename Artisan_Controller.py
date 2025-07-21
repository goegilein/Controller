import serial #pyserial is a library for serial communication
import socket
import threading
import time
from PyQt6 import QtWidgets

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
        self.abs_position = None   
        self.connected=False
        self.origin_offset = [0, 0, 0] # Offset from the work position to the maschine origin
        self._laser_offset = None # Offset for the laser. set in get_maschine_info()
        self._tool_head = None # Tool head type, set in get_maschine_info(). Can be "laser1064" or "laser455"

        self.speed=30
        self.step_width=10
        
        
        self.comand_lock = threading.Lock()
        self.is_homed = False
        self.process_commands = []

        # Initialize the execution thread and events
        self.execution_thread = None
        self.execution_running = threading.Event()
        self.execution_canceled = threading.Event()
        self.execution_running.clear()  # Initially not running

        # Add internal variables thatare tracked and callbacks that can be connected to from a receiving class
        self._current_position = [0, 0, 0]
        self._last_log = ''
        self._process_state = "Idle"  # Possible states: "Idle", "Running", "Paused",

        self.position_changed_callback = None
        self.log_callback = None
        self.process_state_callback = None

    #set a watchers for the current position and last log and process state together with their callbacks
    @property
    def current_position(self):
        return self._current_position

    @current_position.setter
    def current_position(self, value):
        self._current_position = value
        self.abs_position = [value[0] + self.origin_offset[0], value[1] + self.origin_offset[1], value[2] + self.origin_offset[2]]
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

    @property
    def process_state(self):
        return self._process_state
    
    @process_state.setter
    def process_state(self, value):
        self._process_state = value
        if self.process_state_callback:
            self.process_state_callback(value)
    
    @property
    def laser_offset(self):
        return self._laser_offset
    
    @property
    def tool_head(self):
        return self._tool_head

    def set_process_state_callback(self, callback):
        self.process_state_callback = callback

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
        if not self.is_homed:
            dialog = QtWidgets.QMessageBox()
            dialog.setWindowTitle("Homing Required")
            dialog.setText("Artisan must be homed before use.\nPlease ensure the workspace is clear and press OK to continue.")
            dialog.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            dialog.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            dialog.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
            dialog.exec()
            self.home_axis()
            self.is_homed = True
        
        #Identify the maschine tool
        toolhead_info = self.get_toolhead_info()
        if toolhead_info is None:
            return

        #self.work_position = self.get_position()
        self.current_position=self.get_position()
        
        #once connected, constantly track the axis position
        def track_axis():
            try:
                while self.connected:
                    time.sleep(0.1)
                    if self.process_state != "Running": # Only track position if not running a process
                        self.current_position=self.get_position()

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
        

    def send_command(self, command, wait_ok=True):
        """
        Send a G-code command to Snapmaker.
        :param command: G-code command as a string.
        """
        if not self.is_connection_active():
            self.last_log = "Error: Not Connected to Artisan!"
            return
        
        try:
            
            with self.comand_lock:
                if self.connection_type == "usb":
                    self.connection.write((command + '\n').encode())
                else:  # TCP/IP
                    self.connection.sendall((command + '\n').encode())

                if wait_ok:
                    lines = self._read_until_ok()
                    self.last_response = lines if lines else None
                else:
                    self.last_response = self.get_response()
                    
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
    
    def _read_until_ok(self):
            lines = []
            counter = 0
            got_ok = False
            while counter < 1000:  # Limit to 1000 lines to prevent infinite loop
                if self.connection_type == "usb":
                    line = self.connection.readline().decode().strip()
                else:  # TCP/IP
                    line = self.connection.recv(1024).decode().strip()

                if line:
                    lines.append(line)
                if line == "ok":
                    got_ok = True
                    break
            if not got_ok:
                self.last_log = "Error: 'ok' not received from Artisan!"
            return lines

    def move_axis_continuous(self, axis, direction, speed=None, job_save=False):
        """
        Move an axis continuously while the button is pressed.
        :param axis: Axis to move ('X', 'Y', or 'Z').
        :param speed: Speed of movement (positive or negative).
        """
        
        if self.process_state == "Running" and not job_save:
            self.last_log = "Error: Cannot move axis while a process is running. Please pause or cancel the process first."
            return

        if speed is None:
            speed = self.speed

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
    
    def move_axis_step(self, axis, direction, distance=None, speed=None, job_save=False):
        """
        Move an axis by a certain distance.
        :param axis: Axis to move ('X', 'Y', or 'Z').
        :param distance: Distance to move.
        :param speed: Speed of movement.
        """

        if self.process_state == "Running" and not job_save:
            self.last_log = "Error: Cannot move axis while a process is running. Please pause or cancel the process first."
            return


        if speed is None:
            speed = self.speed

        if distance is None:
            distance = self.step_width
        # Set to relative positioning
        self.send_command("G91")

        #limit speed for Z-Axis!
        if axis=="Z" and speed >30:
                speed=30

        # Move the axis
        self.send_command(f"G0 {axis}{direction*distance} F{speed*60}")

        # Switch back to absolute positioning
        self.send_command("G90")

    
    def move_axis_to(self, mode, x, y, z, speed=None, job_save=False):
        """
        Move an axis to a specific position.
        :param axis: Axis to move ('X', 'Y', or 'Z').
        :param position: Position to move to.
        :param speed: Speed of movement.
        """

        if self.process_state == "Running" and not job_save:
            self.last_log = "Error: Cannot move axis while a process is running. Please pause or cancel the process first."
            return

        if speed is None:
            speed = self.speed

        if mode == "absolute":
            # Set to absolute positioning in Workposition Coorinates
            self.send_command("G90")
        elif mode == "relative":
            # Set to relative positioning based on current position
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
    
    def move_axis_absolute(self, x, y, z, speed=None, job_save=False):
        """
        Move the axis in absolute machine coordinates.
        :param x: X-coordinate to move to.
        :param y: Y-coordinate to move to.
        :param z: Z-coordinate to move to.
        :param speed: Speed of movement.
        """

        if self.process_state == "Running" and not job_save:
            self.last_log = "Error: Cannot move axis while a process is running. Please pause or cancel the process first."
            return

        if speed is None:
            speed = self.speed

        # Set to absolute positioning
        self.send_command("G90")

        #limit speed for Z-Axis!
        if speed >30:
            speed=30

        # Adjust coordinates based on origin offset
        x+=self.origin_offset[0]
        y+=self.origin_offset[1]
        z+=self.origin_offset[2]
        # Move the axis
        self.send_command(f"G0 X{x} Y{y} Z{z} F{speed*60}")
    
    def move_to_work_position(self, speed=None, job_save=False):
        """
        Move the axis to the work position.
        :param speed: Speed of movement.
        """

        if self.process_state == "Running" and not job_save:
            self.last_log = "Error: Cannot move to work position while a process is running. Please pause or cancel the process first."
            return

        if speed is None:
            speed = self.speed
        # if self.work_position is None:
        #     self.last_log = "Error: Work position not set."
        #     return
        
        # Move to work position
        self.move_axis_to("absolute", 0, 0, 0, speed=speed)
    
    def home_axis(self, axis='', job_save=False):
        """
        Home an axis.
        :param axis: Axis to home ('X', 'Y', or 'Z').
        """

        if self.process_state not in ["Idle"] and not job_save:
            self.last_log = "Error: Cannot only home axis while Idle"
            return

        self.send_command(f"G28 {axis}") #if axis is empty, all axes will be homed
        self.origin_offset = [0, 0, 0] # Reset origin offset after homing
    
    def get_position(self):
        """
        Get the current position of all axis.
        :return: Current position of all axis.
        """
        self.send_command("M114") # get new position     
        try:
            position = []
            for line in self.last_response:
                if 'X:' in line and 'Y:' in line and 'Z:' in line:
                    # Example response: "X:10.00 Y:20.00 Z:30.00 A:0.000 B:0.000 E:0.00 Count X: 1000 Y: 2000 Z: 3000 A:0 B:0 "
                    # Split the line and extract the values
                    for part in line.split()[0:3]:
                        position.append(float(part.split(":")[1]))
            return position
        except Exception as e:
            self.last_log = f"Failed to get position: {e}"
            return None
    
    def get_absolute_position(self):
        """
        Get the absolute position of all axis.
        :return: Absolute position of all axis.
        """
        pos = self.get_position()
        if pos is None:
            return None
        return [pos[0] + self.origin_offset[0], pos[1] + self.origin_offset[1], pos[2] + self.origin_offset[2]]
        
    def set_work_position(self, job_save=False):
        """
        Set the work position (origin) of the machine.
        :param x: X-coordinate of the work position.
        :param y: Y-coordinate of the work position.
        :param z: Z-coordinate of the work position.
        """

        if self.process_state not in ["Idle"] and not job_save:
            self.last_log = "Error: Can only set a new work position while Idle"
            return

        pos = self.get_position()
        self.origin_offset[0] += pos[0]
        self.origin_offset[1] += pos[1]
        self.origin_offset[2] += pos[2]
        self.send_command("G92 X0 Y0 Z0")  # Set current position as origin
        self.last_log = f"Work position set to absolute: X{self.origin_offset[0]} Y{self.origin_offset[1]} Z{self.origin_offset[2]}"
        #self.work_position = self.get_position()
        # if self.work_position is None: 
        #     self.last_log = "Error: Could not set work position."
        #     return

    def set_speed(self, speed, job_save=False):
        """
        Change the speed of the machine.
        :param speed: New speed to set.
        """

        if self.process_state not in ["Idle"] and not job_save:
            self.last_log = "Error: Can only change speed while Idle"
            return

        if speed < 0 or speed > 100:
            self.last_log = "Error: Speed must be between 0 and 100."
            return
        self.speed = speed

    def set_step_width(self, step_width):
        """
        Change the step width of the machine.
        :param step_width: New step width to set.
        """
        if step_width < 0 or step_width > 100:
            self.last_log = "Error: Step width must be between 0 and 100."
            return
        self.step_width = step_width

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
        if not self.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return
        if not self.process_commands:
            self.last_log = "No commands to execute."
            return
        
        #Here the Process state is set to running. Will use the threading events to control the execution interanlly
        self.process_state = "Running"  # Update state to Running

        # Now apply the laser offset
        if not self.laser_offset:
            self.last_log = "Error: No Laser Offset defined. Cannot start process."
            return
        else:
            self.move_axis_to("relative", self.laser_offset[0], self.laser_offset[1], self.laser_offset[2], speed=30, job_save=True)  # Move to laser offset position
            self.set_work_position(job_save=True)  # Set the current position as the new work position with the laser offset applied

        def execute():
            try:
                
                for command in self.process_commands:

                    self.execution_running.wait()  # Wait if paused

                    if self.execution_canceled.is_set():
                        self.last_log = "Execution canceled. Returning to work position."
                        break

                    self.send_command(command)
                    #self.last_log = '\n'.join(self.last_response)
                    time.sleep(0.01)  # Add a small delay between commands
                else:
                    self.last_log = "Execution completed successfully. Returning to work position."

                #Restore the old work position after execution
                self.move_to_work_position(speed=30,job_save=True)
                self.move_axis_to("relative", -self.laser_offset[0], -self.laser_offset[1], -self.laser_offset[2], speed=30,job_save=True)
                self.set_work_position(job_save=True)  # Reset the work position to the original position
                self.process_state = "Idle"  # Reset state after completion
            except Exception as e:
                self.last_log = f"Error during execution: {e}"
                self.process_state = "Idle"  # Reset state on error
            finally:
                
                self.execution_thread = None

        # Start execution in a separate thread
        if self.process_state == "Idle":
            self.last_log= "Start Processing..."
            self.execution_canceled.clear()
            self.execution_running.set()
            self.execution_thread = threading.Thread(target=execute)
            self.execution_thread.daemon = True  # Make thread a daemon
            self.execution_thread.start()
        else:
            self.last_log = "Execution already in progress or paused. Please cancel or resume first."
            
    def pause_process(self):
        """
        Pause the execution of the NC file.
        """
        if not self.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return
        
        self.execution_running.clear()
        self.last_log = "Execution paused."
        self.process_state = "Paused" # Update state to Paused

    def resume_process(self):
        """
        Resume the execution of the NC file.
        """
        if not self.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return
        
        self.execution_running.set()
        self.last_log = "Execution resumed."
        self.process_state = "Running"  # Update state to Running

    def cancel_process(self):
        """
        Cancel the execution of the NC file.
        """
        if not self.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return
        
        if self.process_state in ["Running", "Paused"]:  # Only allow canceling if running or paused
            self.execution_canceled.set()
            self.execution_running.set() #Ensure the thread can exit if it is waiting
            
            # Wait for the execution thread to finish
            if self.execution_thread and self.execution_thread.is_alive():
                self.execution_thread.join()  # Wait for the thread to finish

            self.last_log = "Execution canceled."

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

    def get_toolhead_info(self):
        """
        Get information about the connected machine.
        set the tool head 
        :return: Machine information as a string.
        """
        if not self.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return None
        
        self.send_command("M1006")
        toolhead_info = self.last_response
        if toolhead_info:
            tool_head = toolhead_info[0].split(":")[1].strip()

            if tool_head == "LASER" and len(toolhead_info) == 39:
                #this ius a 2W 1064 pulsed laser
                self.last_log = "2W 1064 pulsed laser detected. Setting offsets for this laser."
                self._tool_head = "laser1064"
                self._laser_offset = [21.2, -11.3, 0]
            elif tool_head == "LASER" and len(toolhead_info) == 34:
                # this is a 40W 455 cw laser
                self.last_log = "40W 455 cw laser detected. Setting offsets for this laser."
                self._tool_head = "laser455"
                self._laser_offset = None # this has to be measured first!
            else:
                self.last_log = f"Unknown tool head detected: {tool_head}. This is not supported. Closing connection for safety!"
                self._tool_head = None
                self._laser_offset = None
                self.disconnect()
                return None
        else:
            self.last_log = "Error: Could not retrieve machine information. Closing connection for safety! You can try to reconnect."
            self.disconnect()
            return None
        return toolhead_info

class ArtisanJobHandler():
    def __init__(self, controller):
        self.controller = controller
        self.process_state = "Idle"  # Possible states: "Idle", "Running", "Paused", "Canceled"
        self.execution_thread = None
        self.execution_running = threading.Event()
        self.execution_canceled = threading.Event()
        self.process_steps = []  # List to hold G-code commands to execute
        self._last_log = ''
        self._process_state = "Idle"  # Track the process state
        
        # Callbacks for GUI updates
        self.log_callback = None
        self.process_state_callback = None

    @property
    def last_log(self):
        return self._last_log
    @last_log.setter
    def last_log(self, value):
        self._last_log = value
        if self.log_callback:
            self.log_callback(value)

    @property
    def process_state(self):
        return self._process_state
    @process_state.setter
    def process_state(self, value):
        self._process_state = value
        self.controller.process_state = value  # Update the controller's process state
        if self.process_state_callback:
            self.process_state_callback(value)

    def add_process_step(self):
        """
        Add a new process step to the job handler.
        """
        work_position = self.controller.get_absolute_position()
        if work_position is None:
            self.last_log = "Error: Could not retrieve current position."
            return
        if self.process_state != "Idle":
            self.last_log = "Error: Cannot add process step while a process is still active."
            return
        
        step = ProcessStep(work_position)
        self.process_steps.append(step)
        return
    
    def remove_process_step(self, index):
        """
        Remove a process step from the job handler.
        :param index: Index of the process step to remove.
        """
        if self.process_state != "Idle":
            self.last_log = "Error: Cannot remove process step while a process is still active."
            return
        
        if 0 <= index < len(self.process_steps):
            del self.process_steps[index]
            self.last_log = f"Process step {index} removed successfully."
        else:
            self.last_log = "Error: Invalid process step index."
    
    def set_step_wp(self, step_index, new_work_position=None):
        """
        Edit the work position of a process step.
        :param step_index: Index of the process step to edit.
        :param new_work_position: New work position coordinates as a list [x, y, z].
        """
        if self.process_state != "Idle":
            self.last_log = "Error: Cannot edit process step while a process is still active."
            return
        
        if 0 <= step_index < len(self.process_steps):
            if new_work_position is None:
                new_work_position = self.controller.get_absolute_position()
            else:
                self.process_steps[step_index].work_position = new_work_position
        else:
            self.last_log = "Error: Invalid process step index."
    
    def set_step_nc_file(self, step_index, file_path):
        """
        Set the NC file for a process step.
        :param step_index: Index of the process step to set the NC file for.
        :param file_path: Path to the NC file.
        """
        if self.process_state != "Idle":
            self.last_log = "Error: Cannot set NC file while a process is still active."
            return
        
        if 0 <= step_index < len(self.process_steps):
            self.process_steps[step_index].set_nc_file(file_path)
        else:
            self.last_log = "Error: Invalid process step index."

    def start_process(self):
        """
        Execute all process steps in the job handler.
        1. Move to work position of this step
        2. Move to the laser offset position.
        3. Set the current position as the new work position with the laser offset applied.
        4. Execute each command in the process steps.
        5. Restore the old work position after execution.
        6. Move back to the laser offset position.
        """

        if not self.controller.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return
        if not self.process_steps:
            self.last_log = "Error: No process steps defined. Please add process steps before starting."
            return
        # Check if all process steps have a valid work position and a NC file set
        for process_step in self.process_steps:
            if process_step.work_position is None:
                self.last_log = "Error: One or more process steps do not have a valid work position set."
                return
            if not process_step.gcode_file:
                self.last_log = "Error: One or more process steps do not have a valid NC file set."
                return
        
        #Here the Process state is set to running. Will use the threading events to control the execution interanlly
        self.process_state = "Running"  # Update state to Running

        def execute():
            try:
                start_position = self.controller.get_absolute_position()
                for idx, process_step in enumerate(self.process_steps):
                    wp= process_step.work_position
                    commands = process_step.command_list

                    self.controller.move_axis_absolute(wp[0], wp[1], wp[2], speed=30, job_save=True)
                    self.controller.move_axis_to("relative", self.controller.laser_offset[0], self.controller.laser_offset[1], self.controller.laser_offset[2], speed=30, job_save=True)  # Move to laser offset position
                    self.set_work_position(job_save=True)  # Set the current position as the new work position with the laser offset applied
                
                    for command in self.commands:

                        self.execution_running.wait()  # Wait if paused

                        if self.execution_canceled.is_set():
                            self.last_log = "Execution canceled. Returning to work position."
                            break

                        self.controller.send_command(command)
                        #self.last_log = '\n'.join(self.last_response)
                        time.sleep(0.01)  # Add a small delay between commands
                    else:
                        self.last_log = f"Execution of process_step {idx+1} completed successfully."

                #Restore the old position after execution
                self.controller.move_axis_absolute(start_position[0], start_position[1], start_position[2], speed=30, job_save=True)
                self.process_state = "Idle"  # Reset state after completion
            except Exception as e:
                self.last_log = f"Error during execution: {e}"
                self.process_state = "Idle"  # Reset state on error
            finally:
                self.execution_thread = None

        # Start execution in a separate thread
        if self.process_state == "Idle":
            self.last_log= "Start Processing..."
            self.process_state = "Running"  # Set process state to Running
            self.execution_canceled.clear()
            self.execution_running.set()
            self.execution_thread = threading.Thread(target=execute)
            self.execution_thread.daemon = True  # Make thread a daemon
            self.execution_thread.start()
        else:
            self.last_log = "Execution already in progress or paused. Please cancel or resume first."
            
    def pause_process(self):
        """
        Pause the execution of the NC file.
        """
        if not self.controller.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return
        
        self.execution_running.clear()
        self.last_log = "Execution paused."
        self.process_state = "Paused" # Update state to Paused

    def resume_process(self):
        """
        Resume the execution of the NC file.
        """
        if not self.controller.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return
        
        self.execution_running.set()
        self.last_log = "Execution resumed."
        self.process_state = "Running"  # Update state to Running

    def cancel_process(self):
        """
        Cancel the execution of the NC file.
        """
        if not self.controller.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return
        
        if self.process_state in ["Running", "Paused"]:  # Only allow canceling if running or paused
            self.execution_canceled.set()
            self.execution_running.set() #Ensure the thread can exit if it is waiting
            
            # Wait for the execution thread to finish
            if self.execution_thread and self.execution_thread.is_alive():
                self.execution_thread.join()  # Wait for the thread to finish

            self.last_log = "Execution canceled."

class ProcessStep:
    def __init__(self, work_position):
        self.work_position = work_position  # Work position coordinates
        self.gcode_file = None
        self.file_name = None
        self.command_list = []  # List to hold G-code commands for this step

    def set_nc_file(self, file_path):
        """
        Read NC data (G-code) from a file.
        :param file_path: Path to the NC file.
        :return: List of G-code commands.
        """
        try:
            with open(file_path, 'r') as file:
                self.command_list = [line.strip() for line in file if line.strip() and not line.startswith(';')]
                self.gcode_file = file_path
                self.file_name = file_path.split('/')[-1]  # Store the file name
            return f"Successfully read NC file: {file_path}"
        except Exception as e:
            self.gcode_file = None
            self.file_name = None
            self.command_list = []
            return f"Failed to read NC file: {e}"
        
    def set_work_position(self, x, y, z):
        """
        Set the work position for this step.
        :param x: X-coordinate of the work position.
        :param y: Y-coordinate of the work position.
        :param z: Z-coordinate of the work position.
        """
        self.work_position = [x, y, z]