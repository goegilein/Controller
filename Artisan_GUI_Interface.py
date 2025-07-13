from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import pyqtSignal, QObject
from BaseClasses import BaseClass
import datetime

class ArtisanInterface(BaseClass):
    def __init__(self, gui, artisan_controller):
        super().__init__()
        self.gui = gui
        self.artisan_controller = artisan_controller

        #SET BUTTON ACTIONS HERE!!
        #Simple Axis Movement

        self.plus_x_button = gui.plus_x_button
        self.minus_x_button = gui.minus_x_button
        self.plus_y_button = gui.plus_y_button
        self.minus_y_button = gui.minus_y_button
        self.plus_z_button = gui.plus_z_button
        self.minus_z_button = gui.minus_z_button

        self.connect_widget(self.plus_x_button, lambda action: self.move_Axis(action=action,direction=1, axis="X"))
        self.connect_widget(self.minus_x_button, lambda action: self.move_Axis(action=action,direction=-1, axis="X"))
        self.connect_widget(self.plus_y_button, lambda action: self.move_Axis(action=action,direction=1, axis="Y"))
        self.connect_widget(self.minus_y_button, lambda action: self.move_Axis(action=action,direction=-1, axis="Y"))
        self.connect_widget(self.plus_z_button, lambda action: self.move_Axis(action=action,direction=1, axis="Z"))
        self.connect_widget(self.minus_z_button, lambda action: self.move_Axis(action=action,direction=-1, axis="Z"))

        self.axis_step_mode_button = gui.axis_step_mode_button
        self.axis_continuous_mode_button =gui.axis_continuous_mode_button
        self.lock_toggle_buttons(self.axis_step_mode_button, self.axis_continuous_mode_button)
        self.axis_step_size_box = gui.axis_step_size_box
        self.axis_speed_box = gui.axis_speed_box

        #Absdolute Axis 
        self.abs_x_box=gui.abs_x_box
        self.abs_y_box=gui.abs_y_box
        self.abs_z_box=gui.abs_z_box
        self.rel_x_box=gui.rel_x_box
        self.rel_y_box=gui.rel_y_box
        self.rel_z_box=gui.rel_z_box
        self.move_by_x_box=gui.move_by_x_box
        self.move_by_y_box=gui.move_by_y_box
        self.move_by_z_box=gui.move_by_z_box
        self.move_abs_button=gui.move_abs_button
        self.move_rel_button=gui.move_rel_button
        self.set_wp_button=gui.set_wp_button
        self.move_to_wp_button = gui.move_to_wp_button
        self.home_axis_button=gui.home_axis_button

        self.move_abs_button.clicked.connect(self.move_abs)
        self.move_rel_button.clicked.connect(self.move_rel)
        self.move_to_wp_button.clicked.connect(lambda: self.artisan_controller.move_to_work_position(speed=30))
        self.home_axis_button.clicked.connect(self.artisan_controller.home_axis)

        #position tracking
        self.position_emitter = SignalEmitter()
        self.position_emitter.list_signal.connect(self.update_axis_pos)
        self.artisan_controller.set_position_changed_callback(self.threadsafe_update_axis_pos)  # Set the position changed callback to track position
        self.set_wp_button.clicked.connect(self.artisan_controller.set_work_position)

        #Laser Crosshair
        self.laser_crosshair_button = gui.laser_crosshair_button
        self.laser_crosshair_button.clicked.connect(self.toggle_laser_crosshair)

        #Enclosure light
        self.enclosure_light_button = gui.enclosure_light_button
        self.enclosure_light_button.clicked.connect(self.toggle_enclosure_light)

        #Enclosure fan
        self.enclosure_fan_button = gui.enclosure_fan_button
        self.enclosure_fan_button.clicked.connect(self.toggle_enclosure_fan)

        #Air Assist
        self.air_assist_button = gui.air_assist_button
        self.air_assist_button.clicked.connect(self.toggle_air_assist)

        #Process Control
        self.startProcess_button=gui.startProcess_button
        self.startProcess_button.clicked.connect(self.start_process)

        self.cancelProcess_button=gui.cancelProcess_button
        self.cancelProcess_button.clicked.connect(self.cancel_process)

        self.togglePauseProcess_button=gui.togglePauseProcess_button
        self.togglePauseProcess_button.clicked.connect(self.toggle_process_pause)

        self.loadFile_button=gui.loadFile_button
        self.loadFile_button.clicked.connect(self.load_file)

        #Process State stracking
        self.artisan_controller.set_process_state_callback(self.threadsafe_update_process_state)
        self.process_state_emitter = SignalEmitter()
        self.process_state_emitter.string_signal.connect(self.update_process_state)

        #Log tracking
        self.log_textEdit=gui.log_textEdit
        self.log_emitter = SignalEmitter()
        self.log_emitter.string_signal.connect(self.append_log)
        self.artisan_controller.set_log_callback(self.threadsafe_append_log)
    
    def move_Axis(self, action, direction, axis):
        if self.axis_step_mode_button.isChecked():
            move_type="step"
        if self.axis_continuous_mode_button.isChecked():
            move_type="continuous"
        speed=self.axis_speed_box.value()
        step=self.axis_step_size_box.value()

        if action== "released":
            self.artisan_controller.stop_axis()
        elif action == "pressed":
            if move_type == "continuous":
                self.artisan_controller.move_axis_continuous(axis, direction, speed)
            elif move_type == "step":
                self.artisan_controller.move_axis_step(axis, direction, step, speed)
            else:
                print("Error: Invalid move type for Axis.")
    
    def toggle_laser_crosshair(self):
        if self.laser_crosshair_button.isChecked():
            self.artisan_controller.set_laser_crosshair("on")
            self.laser_crosshair_button.setText("Crosshair \nis ON")

        else:
            self.artisan_controller.set_laser_crosshair("off")
            self.laser_crosshair_button.setText("Crosshair \nis OFF")
    
    def threadsafe_update_axis_pos(self, position=None):
        # This method is called from any thread
        self.position_emitter.list_signal.emit(position)

    def update_axis_pos(self, position = None):
        if position is None:
            position = self.artisan_controller.get_position()
        if position is None:
            return
        self.abs_x_box.setValue(self.artisan_controller.abs_position[0])
        self.abs_y_box.setValue(self.artisan_controller.abs_position[1])
        self.abs_z_box.setValue(self.artisan_controller.abs_position[2])
        self.rel_x_box.setValue(self.artisan_controller.current_position[0])
        self.rel_y_box.setValue(self.artisan_controller.current_position[1])
        self.rel_z_box.setValue(self.artisan_controller.current_position[2])

    def move_abs(self):
        x=self.move_by_x_box.value()
        y=self.move_by_y_box.value()
        z=self.move_by_z_box.value() 
        self.artisan_controller.move_axis_absolute(x,y,z, speed=self.axis_speed_box.value())
    
    def move_rel(self):
        x=self.move_by_x_box.value()
        y=self.move_by_y_box.value()
        z=self.move_by_z_box.value()
        self.artisan_controller.move_axis_to('relative',x,y,z, speed=self.axis_speed_box.value())
    
    def toggle_enclosure_light(self):
        if self.enclosure_light_button.isChecked():
            self.artisan_controller.set_enclosure_light("on")
            self.enclosure_light_button.setText("Light \nis ON")
        else:
            self.artisan_controller.set_enclosure_light("off")
            self.enclosure_light_button.setText("Light \nis OFF")

    def toggle_enclosure_fan(self):
        if self.enclosure_fan_button.isChecked():
            self.artisan_controller.set_enclosure_fan("on")
            self.enclosure_fan_button.setText("Fan \nis ON")
        else:
            self.artisan_controller.set_enclosure_fan("off")
            self.enclosure_fan_button.setText("Fan \nis OFF")

    def toggle_air_assist(self):
        if self.air_assist_button.isChecked():
            self.artisan_controller.set_air_assist("on")
            self.air_assist_button.setText("Air Assist \nis ON")
        else:
            self.artisan_controller.set_air_assist("off")
            self.air_assist_button.setText("Air Assist \nis OFF")
    
    def threadsafe_append_log(self, last_log):
        # This method is called from any thread
        self.log_emitter.string_signal.emit(last_log)
        
    def append_log(self, last_log):
        timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
        self.log_textEdit.appendPlainText(f"{timestamp}{last_log}")

    def load_file(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self.gui, "Select File", "", "GCode Files (*.nc);;All Files (*)")
        if file_path:
            self.artisan_controller.read_nc_file(file_path)

    def start_process(self):
        workposition_check = ProcessStartHandler(self.artisan_controller).check_work_position()
        if workposition_check is None:
            self.append_log("Process cancelled by user.")
            return
        else:
            self.append_log(workposition_check)
        self.artisan_controller.start_process()
        self.togglePauseProcess_button.setChecked(False)
        self.togglePauseProcess_button.setText("Pause Process")
    
    def cancel_process(self):
        self.artisan_controller.cancel_process()
        self.togglePauseProcess_button.setChecked(False)
        self.togglePauseProcess_button.setText("Pause Process")
    
    def toggle_process_pause(self):
        if self.togglePauseProcess_button.isChecked():
            self.artisan_controller.pause_process()
            self.togglePauseProcess_button.setText("Resume Process")
        else:
            self.artisan_controller.resume_process()
            self.togglePauseProcess_button.setText("Pause Process")
    
    def threadsafe_update_process_state(self, state):
        # This method is called from any thread
        self.artisan_controller._process_state = state
        self.update_process_state(state)
    
    def update_process_state(self, state):
        if state == "Running":
            self.disable_move_controls()
            self.startProcess_button.setEnabled(False)
            self.cancelProcess_button.setEnabled(True)
            self.togglePauseProcess_button.setEnabled(True)
        elif state == "Paused":
            self.enable_move_controls()
            self.startProcess_button.setEnabled(False)
            self.cancelProcess_button.setEnabled(True)
            self.togglePauseProcess_button.setEnabled(True)
        else:
            self.enable_move_controls()
            self.startProcess_button.setEnabled(True)
            self.cancelProcess_button.setEnabled(False)
            self.togglePauseProcess_button.setEnabled(False)
    
    def disable_move_controls(self):
        self.plus_x_button.setEnabled(False)
        self.minus_x_button.setEnabled(False)
        self.plus_y_button.setEnabled(False)
        self.minus_y_button.setEnabled(False)
        self.plus_z_button.setEnabled(False)
        self.minus_z_button.setEnabled(False)
        self.move_abs_button.setEnabled(False)
        self.move_rel_button.setEnabled(False)
        self.set_wp_button.setEnabled(False)
        self.move_to_wp_button.setEnabled(False)
        self.home_axis_button.setEnabled(False)
    
    def enable_move_controls(self):
        self.plus_x_button.setEnabled(True)
        self.minus_x_button.setEnabled(True)
        self.plus_y_button.setEnabled(True)
        self.minus_y_button.setEnabled(True)
        self.plus_z_button.setEnabled(True)
        self.minus_z_button.setEnabled(True)
        self.move_abs_button.setEnabled(True)
        self.move_rel_button.setEnabled(True)
        self.set_wp_button.setEnabled(True)
        self.move_to_wp_button.setEnabled(True)
        self.home_axis_button.setEnabled(True)
    
class SignalEmitter(QObject):
    list_signal = pyqtSignal(list)
    string_signal = pyqtSignal(str)

class ProcessStartHandler():
    def __init__(self, artisan_controller):
        self.artisan_controller = artisan_controller
    
    def check_work_position(self):  
        present_position = self.artisan_controller.get_position()
        if present_position != [0,0,0]:
            title = "Work Position Mismatch"
            text = "The current position does not match the work position. Do you want to use the current position as the work position?"
            custom_label = "No - Move to Old Work Position"
            result = self.show_custom_message(title, text, custom_label)
            if result == "Yes":
                self.artisan_controller.set_work_position()
                return "Starting Process"
            elif result == custom_label:
                self.artisan_controller.move_to_work_position(speed=30)
                return "Moveing to Old Work Position and Starting Process"
            elif result == "Cancel":
                return None
        else:
            return "Starting Process"
        
    def show_custom_message(self, title, text, custom_label="Custom"):
        msg_box = QMessageBox()
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        msg_box.setIcon(QMessageBox.Icon.Question)
        yes_button = msg_box.addButton(QMessageBox.StandardButton.Yes)
        cancel_button = msg_box.addButton(QMessageBox.StandardButton.Cancel)
        custom_button = msg_box.addButton(custom_label, QMessageBox.ButtonRole.ActionRole)
        msg_box.setDefaultButton(cancel_button)
        msg_box.exec()

        if msg_box.clickedButton() == yes_button:
            return "Yes"
        elif msg_box.clickedButton() == cancel_button:
            return "Cancel"
        elif msg_box.clickedButton() == custom_button:
            return custom_label
        else:
            return "Cancle"
