import threading
import time
from BaseClasses import BaseClass
import os

class ProcessHandler(BaseClass):
    def __init__(self, gui, artisan_controller, rot_motor_controller):
        super().__init__()
        self.gui = gui
        self.controller = artisan_controller
        self.rot_motor_controller = rot_motor_controller
        self.execution_thread = None
        self.execution_running = threading.Event()
        self.execution_canceled = threading.Event()
        self.process_step_list = []  # List to hold process steps
        self._last_log = ''
        self._process_state = "Idle"  # Track the process state
        self._remaining_time = 0
        
        # Callbacks for GUI updates
        self.log_callbacks = []
        self.process_state_callbacks = []
        self.remaining_time_callbacks = []
        
    @property
    def last_log(self):
        return self._last_log
    
    @last_log.setter
    def last_log(self, value):
        self._last_log = value
        if self.log_callbacks:
            for callback in self.log_callbacks:
                callback(value)
    
    def set_log_callback(self, callback):
        self.log_callbacks.append(callback)

    @property
    def process_state(self):
        return self._process_state
    
    @process_state.setter
    def process_state(self, value):
        self._process_state = value
        self.controller.process_state = value  # Update the controller's process state
        if self.process_state_callbacks:
            for callback in self.process_state_callbacks:
                callback(value)
    
    def set_process_state_callback(self, callback):
        self.process_state_callbacks.append(callback)

    @property
    def remaining_time(self):
        return self._remaining_time

    @remaining_time.setter
    def remaining_time(self, value):
        self._remaining_time = value
        if self.remaining_time_callbacks:
            for callback in self.remaining_time_callbacks:
                h=int(value//3600)
                m=int((value%3600)//60)
                s=int(value%60)
                remaining_time_string = f"ETA. - {h}:{m}:{s}"
                callback(remaining_time_string)

    def set_remaining_time_callback(self, callback):
        self.remaining_time_callbacks.append(callback)
       
    def add_process_step(self, name = None):
        """
        Add a new process step to the job handler list.
        """
        if self.process_state != "Idle":
            self.last_log = "Error: Cannot add process step while a process is still active."
            return
        
        work_position = [1,400,400,0] #default
        
        work_position_axis = self.controller.get_absolute_position()

        if work_position_axis is None:
            self.last_log = "Error: Could not retrieve current position of axis. Using Default value"
        else:
            work_position[0:3] = work_position_axis[0:3]

        step = ProcessStep(work_position, name=name)
        self.process_step_list.append(step)

        return step

    
    def remove_process_step(self, process_step):
        """
        Remove a process step from the job handler.
        :param index: Index of the process step to remove.
        """
        if self.process_state != "Idle":
            self.last_log = "Error: Cannot remove process step while a process is still active."
            return False
        else:
            self.process_step_list.remove(process_step)
            return True
 
    def move_step (self, from_idx, to_idx):
        """
        move a step in the process list.
        :param from_idx: the index at which the step is removed
        :param to_index: the new index at which the step is re-inserted
        """

        if self.process_state != "Idle":
            self.last_log = "Error: Cannot change process step work order while a process is still active."
            return
        
        step = self.process_step_list.pop(from_idx)
        self.process_step_list.insert(to_idx, step)
    
    def set_step_wp_to (self, process_step, work_position):
        """
        Set a step's workposition to the specified value [x,y,z]
        :param process_step: Process step to edit.
        :param work_position: List of length 3 with [x,y,z]-Coordinates in absolute position
        """

        if self.process_state != "Idle":
            self.last_log = "Error: Cannot change step work position while a process is still active."
            return None
        else:
            process_step.work_position = work_position
            return work_position

    def set_step_wp_current (self, process_step):
        """
        Set a step's workposition to the current absolute position as received from controller.
        :param process_step: Process step to edit.
        """
        try:
            if self.process_state != "Idle":
                self.last_log = "Error: Cannot change step work position while a process is still active."
                return None
            
            new_work_position_axis = self.controller.get_absolute_position()
            if new_work_position_axis is None:
                self.last_log = "Error: Could not get the axis Position. Using Default value"
                return None
            else:
                process_step.work_position[0:3] = new_work_position_axis[0:3]
            
            if process_step.rot_motor_id is not None:
                rot_pos = self.rot_motor_controller.get_current_angle(process_step.rot_motor_id)[0] #alwas returns a list. for single motor, take first element
                if rot_pos is None:
                    self.last_log = "Error: Could not get the rot motor Position. Using Default value"
                    return None
                else:
                    process_step.work_position[3] = rot_pos
            else:
                process_step.work_position[3] = 0  # reset rot pos if no motor assigned
        except Exception as e:
            self.last_log = f"Error: Could not set work position to current position: {e}"
            return None

        return process_step.work_position
    
    def go_to_step_wp(self, process_step):
        """
        move to a step's workposition in aboslute coordinates
        :param process_step: Process step to move to.
        """
        if self.process_state != "Idle":
            self.last_log = "Error: Cannot move while a process is still active."
            return
        step_wp = process_step.work_position
        self.controller.move_axis_absolute(step_wp[0], step_wp[1], step_wp[2])
        if process_step.rot_motor_id is not None:
            self.rot_motor_controller.move_to_angle(process_step.rot_motor_id, step_wp[3])

    def set_step_nc_file(self, process_step, file_path):
        """
        Change the NC-File for a process step
        :param process_step: Process step to change the file for
        :file_path: Absolute filepath to change to
        """

        if self.process_state != "Idle":
            self.last_log = "Error: Cannot change process step's NC-file while a process is still active."
            return
        
        self.last_log = process_step.set_nc_file(file_path)

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
        if not self.pre_start_check():
            return
        else:
            self.last_log = "Pre-start check passed. Starting process execution."

        def execute():
            try:
                #Here the Process state is set to running. Will use the threading events to control the execution interanlly
                self.process_state = "Running"  # Update state to Running
                start_position = self.controller.get_absolute_position()
                for step_idx, process_step in enumerate(self.process_step_list):


                    #Move to Work Position, then switch to laser tool.
                    self.controller.move_axis_absolute(process_step.work_position[0], process_step.work_position[1], process_step.work_position[2], speed=30, z_save=True, job_save=True)
                    if process_step.rot_motor_id is not None:
                        self.rot_motor_controller.move_to_angle(process_step.rot_motor_id, process_step.work_position[3], wait_for_position=True)
                    if self.execution_canceled.is_set():
                        break
                    self.controller.move_axis_to("relative", self.controller.laser_offset[0], self.controller.laser_offset[1], self.controller.laser_offset[2], speed=30, job_save=True)  # Move to laser offset position
                    if self.execution_canceled.is_set():
                        break
                    self.controller.set_work_position(job_save=True)  # Set the current position as the new work position with the laser offset applied

                    #Execute the step
                    self.execute_process_step(process_step, step_idx)
                    
                    if self.execution_canceled.is_set():
                        break

                #Restore the old position after execution
                self.controller.move_axis_absolute(start_position[0], start_position[1], start_position[2], speed=30, z_save=True, job_save=True)
                self.process_state = "Idle"  # Reset state after completion
                self.remaining_time = sum([step.process_time for step in self.process_step_list]) # reset remaining time
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
    
    def pre_start_check(self):
        #check if controller is connected
        if not self.controller.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return False
        if not self.process_step_list:
            self.last_log = "Error: No process steps defined. Please add process steps before starting."
            return False
        
        # Check if all process steps have valid data set
        for process_step in self.process_step_list:
            #check work position and nc file
            if process_step.work_position is None:
                self.last_log = "Error: One or more process steps do not have a valid work position set."
                return False
            if not process_step.nc_file:
                self.last_log = "Error: One or more process steps do not have a valid NC file set."
                return False
            #check if jcode steps have rot motor assigned if needed
            if process_step.file_type == "jcode" and process_step.rot_motor_id is None:
                with open(process_step.nc_file, 'r') as file:
                    jcode_commands = [line.strip() for line in file if line.strip() and not line.startswith(';')]
                r = 0
                for command in jcode_commands:
                    if command.startswith("J0"):
                        parts = command.split()
                        for part in parts:
                            if part.startswith("R"):
                                r = float(part[1:])
                        if r != 0:
                            self.last_log = f"Error: Process step with J-code file {process_step.nc_file} requires a rotational motor assignment."
                            return False

        return True
    
    def execute_process_step(self, process_step: ProcessStep, step_idx: int):
        try:
            self.last_log = f"Executing Process Step: {process_step.name} with estimated process time: {process_step.process_time:.2f}s"

            for command in process_step.jcode_command_list:
                if command.startswith("J0"):
                    parts = command.split()
                    for part in parts:
                        if part.startswith("X"):
                            x = float(part[1:])+process_step.work_position[0]+self.controller.laser_offset[0]
                        elif part.startswith("Y"):
                            y = float(part[1:])+process_step.work_position[1]+self.controller.laser_offset[1]
                        elif part.startswith("Z"):
                            z = float(part[1:])+process_step.work_position[2]+self.controller.laser_offset[2]
                        elif part.startswith("R"):
                            r = float(part[1:])+process_step.work_position[3]

                    self.controller.move_axis_absolute(x, y, z, job_save=True)
                    self.controller.set_work_position(job_save=True)
                    if process_step.rot_motor_id is not None:
                        self.rot_motor_controller.move_to_angle(process_step.rot_motor_id, r, wait_for_position=True)
                    time.sleep(0.5)  # Wait for movement to ensure stability
                elif command.startswith("J1"):
                    parts = command.split()
                    gcode_idx = int(parts[1])
                    self.execute_gcode(process_step.command_lists[gcode_idx], process_step.time_lists[gcode_idx], gcode_id=f"{step_idx+1}_{gcode_idx+1}")
            
            self.last_log = f"Execution of Process Step: {process_step.name} completed successfully."
        except Exception as e:
            self.last_log = f"Failed to execute J-code file: {e}"
            

    def execute_gcode(self, gcode_commands, time_list, gcode_id="0"):
        """
        Execute a single gcode file immediately.
        :param gcode_commands: List of gcode commands to execute.
        :param time_list: List of times for each command.
        :param gcode_id: ID of the gcode file for logging purposes.
        """

        for idx, command in enumerate(gcode_commands):

            self.execution_running.wait()  # Wait if paused

            if self.execution_canceled.is_set():
                self.last_log = "Execution canceled. Returning to work position."
                break

            self.controller.send_command(command)

            self.remaining_time=round((self.remaining_time-time_list[idx]) * (self.remaining_time > 0)) #
            #time.sleep(time_list[idx]*0.5)  # Add a delay between commands. Factor 0.5 probably accounts for wait for ok or smth like that
        else:
            self.controller.add_sync_position(text=f"step_{gcode_id}_done", timeout=60)  # Ensure all movements are finished before proceeding
            time.sleep(0.5)  # Wait a bit to ensure the sync position is reached
            if self.controller.last_log == f"Error: step_{gcode_id}_done not received from Artisan!":
                self.cancel_process()

 
    # def execute_jcode_file(self, file_path, rot_motor_id, step_laser_wp, command_lists, time_lists, step_id="0"):
    #     """
    #     Execute a J-code file which may reference multiple gcode files.
    #     :param file_path: Path to the J-code file.
    #     :param step_id: ID of the step for logging purposes.
    #     """        
    #     try:
    #         with open(file_path, 'r') as file:
    #             jcode_commands = [line.strip() for line in file if line.strip() and not line.startswith(';')]
            
    #         self.last_log = f"Executing J-code file: {file_path}"

    #         g_code_files_counter = 0
    #         for command in jcode_commands:
    #             if command.startswith("J0"):
    #                 parts = command.split()
    #                 for part in parts:
    #                     if part.startswith("X"):
    #                         x = float(part[1:])+step_laser_wp[0]
    #                     elif part.startswith("Y"):
    #                         y = float(part[1:])+step_laser_wp[1]
    #                     elif part.startswith("Z"):
    #                         z = float(part[1:])+step_laser_wp[2]
    #                     elif part.startswith("R"):
    #                         r = float(part[1:])+step_laser_wp[3]

    #                 self.controller.move_axis_absolute(x, y, z, job_save=True)
    #                 self.controller.set_work_position(job_save=True)
    #                 if rot_motor_id is not None:
    #                     self.rot_motor_controller.move_to_angle(rot_motor_id, r, wait_for_position=True)
    #                 time.sleep(0.5)  # Wait for movement to ensure stability
    #             elif command.startswith("J1"):
    #                 parts = command.split()
    #                 nc_file = parts[1]
    #                 self.execute_gcode(command_lists[g_code_files_counter], time_lists[g_code_files_counter], step_id=step_id+f"_g-code-file{g_code_files_counter+1}")
    #                 g_code_files_counter += 1
            
    #         self.last_log = f"Execution of J-code file {file_path} completed successfully."
    #     except Exception as e:
    #         self.last_log = f"Failed to execute J-code file: {e}"
            
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
    
    def recalc_process_params(self):
        remaining_time = 0
        for step in self.process_step_list:
            remaining_time += step.process_time
        self.remaining_time = remaining_time

    def run_bounding_box(self, step_idx, in_laser_coord=False):
        process_step = self.process_step_list[step_idx]
        bounding_box = process_step.bounding_box
        if in_laser_coord: # offset the bounding box by laser offset
            bounding_box[0][0]+=self.controller.laser_offset[0]
            bounding_box[0][1]+=self.controller.laser_offset[0]
            bounding_box[1][0]+=self.controller.laser_offset[1]
            bounding_box[1][1]+=self.controller.laser_offset[1]

        wp = process_step.work_position

        #make sure to move to work position first
        self.controller.move_axis_absolute(wp[0], wp[1], wp[2])

        #set workposition so we can work with absolute coordinates inside the workposition coordinate system
        self.controller.set_work_position()

        #run the upper X/Y bounding Box
        self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][1], bounding_box[2][1])
        self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][0], bounding_box[2][1])
        self.controller.move_axis_to("absolute", bounding_box[0][1], bounding_box[1][0], bounding_box[2][1])
        self.controller.move_axis_to("absolute", bounding_box[0][1], bounding_box[1][1], bounding_box[2][1])
        self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][1], bounding_box[2][1])

        #if it is not flat, also run the lower X/Y bounding Box
        if bounding_box[2][0] != bounding_box[2][1]:
            self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][1], bounding_box[2][0])
            self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][0], bounding_box[2][0])
            self.controller.move_axis_to("absolute", bounding_box[0][1], bounding_box[1][0], bounding_box[2][0])
            self.controller.move_axis_to("absolute", bounding_box[0][1], bounding_box[1][1], bounding_box[2][0])
            self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][1], bounding_box[2][0])

        #return to the work position
        self.controller.move_axis_absolute(wp[0], wp[1], wp[2])
    

        
class ProcessStep:
    def __init__(self, work_position, name=None):
        self.work_position = work_position  # Work position coordinates
        self.name = name
        self.nc_file = None
        self.file_type = ""
        self.file_name = None
        self.jcode_command_list = []  # List to hold J-code commands for this step
        self.process_time = 0  # in seconds
        self.time_lists = []  # in seconds for each command^
        self.command_lists = []  # list of lists of commands if multiple gcode files are referenced
        self.bounding_box = [[0,0],[0,0],[0,0],[0,0]]  #x min max, y min max, z min max
        self.rot_motor_id = None  # ID of the rotational motor if used

    def set_nc_file(self, file_path):
        """
        Read NC data (G-code) from a file.
        :param file_path: Path to the NC file.
        :return: List of G-code commands.
        """   
        ncCode_interpreter = NCCodeInterpreter()

        try:

            self.command_lists, self.time_lists, self.bounding_box, self.file_type, self.jcode_command_list = ncCode_interpreter.interpret_nc_file(file_path)
            self.process_time = sum(map(sum, self.time_lists))
            self.nc_file = file_path
            return f"Successfully read singe Data file: {file_path} of type {self.file_type} with process time {self.process_time:.2f}s"

        except Exception as e:
            self.nc_file = None
            self.file_name = None
            self.jcode_command_list = []
            self.process_time = 0
            self.time_lists = []
            self.bounding_box = [[0,0],[0,0],[0,0],[0,0]]
            return f"Failed to read Data file: {e}"
        
    def set_work_position(self, work_position):
        """
        Set the work position for this step.
        :param x: X-coordinate of the work position.
        :param y: Y-coordinate of the work position.
        :param z: Z-coordinate of the work position.
        """
        self.work_position = work_position


import numpy as np
class NCCodeInterpreter():
    def interpret_nc_file(self, file_path):
        """
        Interpret an NC file (.nc or .jcode). Always parses into a compacted jcode style, where all gcode files are stored as command lists and time lists with an associated J1 command pointing to this list.
        Supported file types: G-code (.nc) and J-code (.jcode).
        :param file_path: Path to the NC file.
        :return:jcode_command_list, command_lists, time_lists, bounding_box
        """
        #first get a list of pointers to gcode files
        gcode_file_list = []# this is a list of [file_path, wp]
        jcode_command_list = []
        wp = [0,0,0,0]  #default work position
        gcode_counter = 0
        if file_path.lower().endswith('.nc'):
            file_type = "gcode"
            gcode_file_list.append([file_path,wp])
            # with open(file_path, 'r') as file:
            #     gcode_commands = [line.strip() for line in file if line.strip() and not line.startswith(';')]
            jcode_command_list.append(f"J1 {gcode_counter}")
        elif file_path.lower().endswith('.jcode'):
            file_type = "jcode"
            with open(file_path, 'r') as file:
                jcode_commands = [line.strip() for line in file if line.strip() and not line.startswith(';')]
            for command in jcode_commands:
                if command.startswith("J0"):
                    parts = command.split()
                    for part in parts:
                        if part.startswith("X"):
                            wp[0] = float(part[1:])
                        elif part.startswith("Y"):
                            wp[1] = float(part[1:])
                        elif part.startswith("Z"):
                            wp[2] = float(part[1:])
                        elif part.startswith("R"):
                            wp[3] = float(part[1:])
                    
                    jcode_command_list.append(command)
                    
                elif command.startswith("J1"):
                    parts = command.split()
                    gcode_file_list.append([parts[1],wp])  # The G-code file name is the second part
                    jcode_command_list.append(f"J1 {gcode_counter}")
                    gcode_counter += 1


        #now read all gcode files and extract time_lists and bounding box
        time_lists = []
        command_lists = []
        combined_bounding_box = [[0,0],[0,0],[0,0],[0,0]]
        for gcode_file in gcode_file_list:
            file_path = gcode_file[0]
            wp = gcode_file[1]
            try:
                with open(file_path, 'r') as file:
                    gcode_commands = [line.strip() for line in file if line.strip() and not line.startswith(';')]
                # command_list, time_list, bounding_box = self.interpret_gcode(gcode_commands, wp=wp[0:3])
                command_list, time_list, bounding_box = self.interpret_gcode_with_segmentation(gcode_commands, wp=wp[0:3])
                command_lists.append(command_list)
                time_lists.append(time_list)
                #update bounding box
                combined_bounding_box[0][0] = min(combined_bounding_box[0][0], bounding_box[0][0])
                combined_bounding_box[0][1] = max(combined_bounding_box[0][1], bounding_box[0][1])
                combined_bounding_box[1][0] = min(combined_bounding_box[1][0], bounding_box[1][0])
                combined_bounding_box[1][1] = max(combined_bounding_box[1][1], bounding_box[1][1])
                combined_bounding_box[2][0] = min(combined_bounding_box[2][0], bounding_box[2][0])
                combined_bounding_box[2][1] = max(combined_bounding_box[2][1], bounding_box[2][1])
                combined_bounding_box[3][0] = min(combined_bounding_box[3][0], wp[3])
                combined_bounding_box[3][1] = max(combined_bounding_box[3][1], wp[3])

            except Exception as e:
                print(f"Failed to read G-code file {gcode_file}: {e}")
        
        return command_lists, time_lists, combined_bounding_box, file_type, jcode_command_list

    def interpret_gcode(self, command_list, wp= [0,0,0]):
        """
        Returns all G0 and G1 commands as arrays of doubles: [x, y, z, speed].
        Only commands with X, Y, Z, and F (speed) are included.
        """
        time_list = [0.01 for _ in command_list]
        bounding_box = [[0,0],[0,0],[0,0]]  # x min max, y min max, z min max
        f=6000
        x, y, z = wp[0], wp[1], wp[2]
        x_new, y_new, z_new = x, y, z
        for idx,command in enumerate(command_list):
            if command.startswith("G0") or command.startswith("G1"):
                # Example: "G1 X10.0 Y20.0 Z5.0 F1200"
                parts = command.split()
                for part in parts:
                    if part.startswith("X"):
                        x_new = float(part[1:])+wp[0]
                    elif part.startswith("Y"):
                        y_new = float(part[1:])+wp[1]
                    elif part.startswith("Z"):
                        z_new = float(part[1:])+wp[2]
                    elif part.startswith("F"):
                        f = float(part[1:])
                command_time = np.sqrt((x-x_new)**2+(y-y_new)**2+(z-z_new)**2)/f*60
                bounding_box[0][0] = min(bounding_box[0][0], x_new)
                bounding_box[0][1] = max(bounding_box[0][1], x_new)
                bounding_box[1][0] = min(bounding_box[1][0], y_new)
                bounding_box[1][1] = max(bounding_box[1][1], y_new)
                bounding_box[2][0] = min(bounding_box[2][0], z_new)
                bounding_box[2][1] = max(bounding_box[2][1], z_new)
                if command_time>0.01:
                    time_list[idx]=command_time
                x=x_new
                y=y_new
                z=z_new
  
        return command_list, time_list, bounding_box
    
    def interpret_gcode_with_segmentation(self, command_list, wp=[0, 0, 0]):
        """
        Parses G-code, segments long commands, and calculates execution times.
        Preserves all original command parameters (E, F, P, S, etc.).
        Returns:
            new_command_list: The segmented G-code strings.
            time_list: The expected execution time for each command.
            bounding_box: [[x_min, x_max], [y_min, y_max], [z_min, z_max]]
        """
        new_command_list = []
        time_list = []
        
        bounding_box = [[float('inf'), float('-inf')], 
                        [float('inf'), float('-inf')], 
                        [float('inf'), float('-inf')]] 
        
        f = 6000.0
        x, y, z, e = wp[0], wp[1], wp[2], 0.0
        
        for command in command_list:
            # Match G0/G1 commands safely (avoids matching G10, G11, etc.)
            if command.startswith("G0 ") or command.startswith("G1 ") or command in ["G0", "G1"]:
                parts = command.split()
                cmd_type = parts[0]
                
                x_new, y_new, z_new, e_new = x, y, z, e
                
                # Track which axes are actually moving in this specific line
                active_axes = {'X': False, 'Y': False, 'Z': False, 'E': False}
                static_params = [] # Holds F, P, S, etc.
                
                for part in parts[1:]:
                    if not part: continue
                    letter = part[0].upper()
                    
                    if letter == "X":
                        x_new = float(part[1:]) + wp[0]
                        active_axes['X'] = True
                    elif letter == "Y":
                        y_new = float(part[1:]) + wp[1]
                        active_axes['Y'] = True
                    elif letter == "Z":
                        z_new = float(part[1:]) + wp[2]
                        active_axes['Z'] = True
                    elif letter == "E":
                        e_new = float(part[1:])
                        active_axes['E'] = True
                    elif letter == "F":
                        f = float(part[1:])
                        static_params.append(part) # Add to static params
                    else:
                        # Catch-all for P, S, or any other proprietary Marlin letters
                        static_params.append(part)
                
                # Calculate distance. If X/Y/Z don't move, check if E moves (e.g., Retraction)
                xyz_dist = np.sqrt((x - x_new)**2 + (y - y_new)**2 + (z - z_new)**2)
                distance = xyz_dist if xyz_dist > 0 else abs(e_new - e)
                
                command_time = (distance / f) * 60 if f > 0 else 0.01
                
                # Update bounding box only if the axis actually moved
                if active_axes['X']:
                    bounding_box[0][0] = min(bounding_box[0][0], x_new)
                    bounding_box[0][1] = max(bounding_box[0][1], x_new)
                if active_axes['Y']:
                    bounding_box[1][0] = min(bounding_box[1][0], y_new)
                    bounding_box[1][1] = max(bounding_box[1][1], y_new)
                if active_axes['Z']:
                    bounding_box[2][0] = min(bounding_box[2][0], z_new)
                    bounding_box[2][1] = max(bounding_box[2][1], z_new)
                
                # --- SEGMENTATION LOGIC ---
                if command_time > 1.0:
                    num_segments = int(np.ceil(command_time))
                    segment_time = command_time / num_segments
                    
                    for step in range(1, num_segments + 1):
                        progress = step / num_segments
                        segment_parts = [cmd_type]
                        
                        # Interpolate and append ONLY the axes present in the original command
                        if active_axes['X']:
                            step_x = x + (x_new - x) * progress
                            segment_parts.append(f"X{step_x - wp[0]:.3f}")
                        if active_axes['Y']:
                            step_y = y + (y_new - y) * progress
                            segment_parts.append(f"Y{step_y - wp[1]:.3f}")
                        if active_axes['Z']:
                            step_z = z + (z_new - z) * progress
                            segment_parts.append(f"Z{step_z - wp[2]:.3f}")
                        if active_axes['E']:
                            step_e = e + (e_new - e) * progress
                            # E (Extruder) usually requires higher precision than X/Y/Z
                            segment_parts.append(f"E{step_e:.5f}")
                        
                        # Append all non-interpolated parameters (F, P, S, etc.)
                        segment_parts.extend(static_params)
                        
                        new_command_list.append(" ".join(segment_parts))
                        time_list.append(segment_time)
                else:
                    # Command is short, keep the original string untouched
                    new_command_list.append(command)
                    time_list.append(max(command_time, 0.01))
                
                # Update current position state
                x, y, z, e = x_new, y_new, z_new, e_new
                
            else:
                # Non-motion commands
                new_command_list.append(command)
                time_list.append(0.01)

        # Clean up bounding box if file was empty or had no motion
        for i in range(3):
            if bounding_box[i][0] == float('inf'):
                bounding_box[i] = [0, 0]

        return new_command_list, time_list, bounding_box