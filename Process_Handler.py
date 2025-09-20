import threading
import time
from BaseClasses import BaseClass

class ProcessHandler(BaseClass):
    def __init__(self, gui, controller):
        super().__init__()
        self.gui = gui
        self.controller = controller
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
       
    def add_process_step(self):
        """
        Add a new process step to the job handler list.
        """
        if self.process_state != "Idle":
            self.last_log = "Error: Cannot add process step while a process is still active."
            return
        
        work_position = self.controller.get_absolute_position()

        if work_position is None:
            self.last_log = "Error: Could not retrieve current position. Setting Default value"
            work_position = [100,100,100]
        
        
        step = ProcessStep(work_position)
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

        if self.process_state != "Idle":
            self.last_log = "Error: Cannot change step work position while a process is still active."
            return None
        
        new_work_position = self.controller.get_absolute_position()
        if new_work_position is None:
            self.last_log = "Error: Could not get the retrieve Position."
            return None
        else:
            process_step.work_position = new_work_position
            return new_work_position

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
        if not self.controller.connected:
            self.last_log = "Error: Not connected to Artisan!"
            return
        if not self.process_step_list:
            self.last_log = "Error: No process steps defined. Please add process steps before starting."
            return
        
        # Check if all process steps have a valid work position and a NC file set
        for process_step in self.process_step_list:
            if process_step.work_position is None:
                self.last_log = "Error: One or more process steps do not have a valid work position set."
                return
            if not process_step.gcode_file:
                self.last_log = "Error: One or more process steps do not have a valid NC file set."
                return

        def execute():
            try:
                #Here the Process state is set to running. Will use the threading events to control the execution interanlly
                self.process_state = "Running"  # Update state to Running
                start_position = self.controller.get_absolute_position()
                for step_idx, process_step in enumerate(self.process_step_list):

                    #get wp, commands, and time for each command
                    wp= process_step.work_position
                    commands = process_step.command_list
                    time_list=process_step.time_list

                    #Move to Work Position, then switch to laser tool.
                    pos_now=self.controller.get_absolute_position()
                    self.controller.move_axis_absolute(wp[0], wp[1], wp[2], speed=30, job_save=True)
                    time.sleep(np.sqrt((wp[0]-pos_now[0])**2 + (wp[1]-pos_now[1])**2 + (wp[2]-pos_now[2])**2)/30*0.5)
                    if self.execution_canceled.is_set():
                        break
                    self.controller.move_axis_to("relative", self.controller.laser_offset[0], self.controller.laser_offset[1], self.controller.laser_offset[2], speed=30, job_save=True)  # Move to laser offset position
                    time.sleep(np.sqrt(self.controller.laser_offset[0]**2 + self.controller.laser_offset[1]**2 + self.controller.laser_offset[2]**2)/30*0.5)
                    if self.execution_canceled.is_set():
                        break
                    self.controller.set_work_position(job_save=True)  # Set the current position as the new work position with the laser offset applied


                    for idx, command in enumerate(commands):

                        self.execution_running.wait()  # Wait if paused

                        if self.execution_canceled.is_set():
                            self.last_log = "Execution canceled. Returning to work position."
                            break

                        self.controller.send_command(command)
                        # time_passed+=time_list[idx]
                        self.remaining_time=round((self.remaining_time-time_list[idx]) * (self.remaining_time > 0)) #
                    

                        time.sleep(time_list[idx]*0.5)  # Add a delay between commands. Factor 0.5 probably accounts for wait for ok or smth like that
                    else:
                        #self.controller.add_sync_position(text=f"step_{step_idx+1}_done", timeout=10)  # Ensure all movements are finished before proceeding
                        self.last_log = f"Execution of process_step {step_idx+1} completed successfully."
                    
                    if self.execution_canceled.is_set():
                        break

                #Restore the old position after execution
                self.controller.move_axis_absolute(start_position[0], start_position[1], start_position[2], speed=30, job_save=True)
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

    def run_bounding_box(self, step_idx):
        process_step = self.process_step_list[step_idx]
        bounding_box = process_step.bounding_box
        wp = process_step.work_position

        #make sure to move to work position first
        self.controller.move_axis_absolute(wp[0], wp[1], wp[2], speed=30)

        #set workposition so we can work with absolute coordinates inside the workposition coordinate system
        self.controller.set_work_position()

        #run the upper X/Y bounding Box
        self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][1], bounding_box[2][1], speed=30)
        self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][0], bounding_box[2][1], speed=30)
        self.controller.move_axis_to("absolute", bounding_box[0][1], bounding_box[1][0], bounding_box[2][1], speed=30)
        self.controller.move_axis_to("absolute", bounding_box[0][1], bounding_box[1][1], bounding_box[2][1], speed=30)

        #if it is not flat, also run the lower X/Y bounding Box
        if bounding_box[2][0] != bounding_box[2][1]:
            self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][1], bounding_box[2][0], speed=30)
            self.controller.move_axis_to("absolute", bounding_box[0][0], bounding_box[1][0], bounding_box[2][0], speed=30)
            self.controller.move_axis_to("absolute", bounding_box[0][1], bounding_box[1][0], bounding_box[2][0], speed=30)
            self.controller.move_axis_to("absolute", bounding_box[0][1], bounding_box[1][1], bounding_box[2][0], speed=30)

        #return to the work position
        self.controller.move_axis_absolute(wp[0], wp[1], wp[2], speed=30)


        
class ProcessStep:
    def __init__(self, work_position):
        self.work_position = work_position  # Work position coordinates
        self.gcode_file = None
        self.file_name = None
        self.command_list = []  # List to hold G-code commands for this step
        self.process_time = 0  # in seconds
        self.time_list = []  # in seconds for each command
        self.bounding_box = [[0,0],[0,0],[0,0]]  #x min max, y min max, z min max

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
            # when loading a new file, calculate the time list
            self.time_list, self.bounding_box = GCodeInterpreter.interpret_code(self.command_list)
            self.process_time = sum(self.time_list)
            return f"Successfully read NC file: {file_path}"
        except Exception as e:
            self.gcode_file = None
            self.file_name = None
            self.command_list = []
            self.process_time = 0
            self.time_list = []
            self.bounding_box = [[0,0],[0,0],[0,0]]
            return f"Failed to read NC file: {e}"
        
    def set_work_position(self, work_position):
        """
        Set the work position for this step.
        :param x: X-coordinate of the work position.
        :param y: Y-coordinate of the work position.
        :param z: Z-coordinate of the work position.
        """
        self.work_position = work_position


import numpy as np
class GCodeInterpreter():
    def interpret_code(command_list):
        """
        Returns all G0 and G1 commands as arrays of doubles: [x, y, z, speed].
        Only commands with X, Y, Z, and F (speed) are included.
        """
        time_list = [0.01 for _ in command_list]
        bounding_box = [[0,0],[0,0],[0,0]]  # x min max, y min max, z min max
        f=6000
        x = y = z = 0
        x_new = y_new = z_new = 0
        for idx,command in enumerate(command_list):
            if command.startswith("G0") or command.startswith("G1"):
                # Example: "G1 X10.0 Y20.0 Z5.0 F1200"
                parts = command.split()
                for part in parts:
                    if part.startswith("X"):
                        x_new = float(part[1:])
                    elif part.startswith("Y"):
                        y_new = float(part[1:])
                    elif part.startswith("Z"):
                        z_new = float(part[1:])
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
  
        return time_list, bounding_box

