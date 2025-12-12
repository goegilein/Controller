from PyQt6 import uic
from PyQt6.QtWidgets import QListWidgetItem, QFileDialog
from BaseClasses import BaseClass, TextLogger, SignalEmitter
from PyQt6.QtGui import QIcon#
import re

class ProcessInterface(BaseClass):
    def __init__(self, gui, process_handler):
        super().__init__()
        self.gui = gui
        self.process_handler = process_handler
        self.widget_path = "GUI_files/process_step_widget.ui"

        # Add gui callbacks
        self.add_process_step_button = gui.add_process_step_button
        self.add_process_step_button.clicked.connect(self.add_process_step)

        self.process_steps_listWidget = gui.process_steps_listWidget
        self.process_steps_listWidget.model().rowsMoved.connect(self.on_rows_moved)

        # Process Control
        self.toggle_process_button=gui.toggle_process_button
        self.toggle_process_button.clicked.connect(self.toggle_process)

        self.cancel_process_button=gui.cancel_process_button
        self.cancel_process_button.clicked.connect(self.cancel_process)

        self.run_bounding_box_button =gui.run_bounding_box_button
        self.run_bounding_box_button.clicked.connect(self.run_bounding_box)
        self.bounding_box_step_combobox = gui.bounding_box_step_combobox
    

        #Log tracking
        self.log_textEdit=gui.log_textEdit
        logger = TextLogger(log_object="Process", log_widget=self.log_textEdit)
        self.process_handler.set_log_callback(logger.log)

        # update UI for Process State
        self.process_state_edit = gui.process_state_edit
        process_logger = TextLogger(log_object="Process", log_widget=self.process_state_edit, add_stamp=False)
        self.process_handler.set_process_state_callback(process_logger.log)
        self.process_handler.set_process_state_callback(self.update_process_state)

        # update UI for Remaining Time
        self.time_remaining_edit = gui.time_remaining_edit
        time_remaining_logger = TextLogger(log_object="Process", log_widget=self.time_remaining_edit, add_stamp=False)
        self.process_handler.set_remaining_time_callback(time_remaining_logger.log)

        #update available rot motors in combobox when changed
        self.process_handler.rot_motor_controller.set_connected_callback(lambda connected: self.set_available_rot_motors())


    def add_process_step(self):
        """
        Add a new process step to the job handler and link a GUI element to it
        """
        
        step = self.process_handler.add_process_step()

        # put widget it into the list
        widget = uic.loadUi(self.widget_path)
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.process_steps_listWidget.addItem(item)
        self.process_steps_listWidget.setItemWidget(item, widget)

        widget.wp_x_spinbox.setValue(step.work_position[0])
        widget.wp_y_spinbox.setValue(step.work_position[1])
        widget.wp_z_spinbox.setValue(step.work_position[2])

        widget.wp_x_spinbox.valueChanged.connect(lambda _, s=step, w=widget: self.set_step_wp(s,w))
        widget.wp_y_spinbox.valueChanged.connect(lambda _, s=step, w=widget: self.set_step_wp(s,w))
        widget.wp_z_spinbox.valueChanged.connect(lambda _, s=step, w=widget: self.set_step_wp(s,w))
        widget.wp_r_spinbox.valueChanged.connect(lambda _, s=step, w=widget: self.set_step_wp(s,w))
        
        widget.remove_button.clicked.connect(lambda _, s=step, w=widget: self.remove_process_step(s,w))
        widget.load_file_button.clicked.connect(lambda _, s=step, w=widget: self.set_step_nc_file(s,w))
        widget.step_name_edit.setText(f"Process Step {len(self.process_handler.process_step_list)}")
        widget.set_current_pos_button.clicked.connect(lambda _, s=step, w=widget, b=True: self.set_step_wp(s,w,b))
        widget.go_to_wp_button.clicked.connect(lambda _, s=step: self.go_to_step_wp(s))

        #rotation motor
        self.set_available_rot_motors([widget])
        widget.rot_mot_combobox.currentTextChanged.connect(lambda _, s=step, w=widget: self.set_rot_motor_id(s,w))


        #position tracking Axis
        position_emitter = SignalEmitter()

        def update_axis_pos(position = None):
            abs_pos = self.process_handler.controller.abs_position

            widget.rel_x_spinbox.setValue(abs_pos[0]-step.work_position[0])
            widget.rel_y_spinbox.setValue(abs_pos[1]-step.work_position[1])
            widget.rel_z_spinbox.setValue(abs_pos[2]-step.work_position[2])
        
        def threadsave_update_axies(position):
            position_emitter.list_signal.emit(position)
            
        position_emitter.list_signal.connect(update_axis_pos)
        self.process_handler.controller.add_position_changed_callback(threadsave_update_axies)  # Set the position changed callback to track position

        #refresh combobox for bounding box run
        self.bounding_box_step_combobox.clear()
        self.bounding_box_step_combobox.addItem('All')
        for idx,steps in enumerate(self.process_handler.process_step_list):
            self.bounding_box_step_combobox.addItem(f'step {idx+1}')

    def remove_process_step(self, process_step, widget):
        """
        Remove a process step from the job handler and update the UI.
        :param index: Index of the process step to remove.
        """
        removed=self.process_handler.remove_process_step(process_step)
        
        if removed: #update the gui as well
            for i in range(self.process_steps_listWidget.count()):
                item = self.process_steps_listWidget.item(i)
                if self.process_steps_listWidget.itemWidget(item) is widget:
                    self.process_steps_listWidget.takeItem(i)
                    # also remove from backend
                    #del self.process_step_list[i]
                    #self.process_step_list.remove(process_step)
                    widget.deleteLater()
                    break
        
        #refresh combobox for bounding box run
        self.bounding_box_step_combobox.clear()
        self.bounding_box_step_combobox.addItem('All')
        for idx,steps in enumerate(self.process_handler.process_step_list):
            self.bounding_box_step_combobox.addItem(f'step {idx+1}')

    def on_rows_moved(self, parent, start, end, dest, row):
        """
        Keep track in backend line of process list when UI elements are moved
        """
        # e.g. start==2, end==2, row==5 means item 2 moved to after index 4
        if row > start:
            row -= 1
        self.process_handler.move_step(start, row)

    
    def set_step_wp(self, process_step, widget, set_to_current=False):
        """
        Change a Process step's workposition based on UI input.
        :param process_step: handle to the process step of type ProcessStep.
        :param widget: handle to the gui widget in the list.
        """
        if set_to_current:
            new_work_position = self.process_handler.set_step_wp_current(process_step)
            if new_work_position is None:
                return
            else:
                #block signal to avoid recursion
                widget.wp_x_spinbox.blockSignals(True)
                widget.wp_y_spinbox.blockSignals(True)
                widget.wp_z_spinbox.blockSignals(True)
                widget.wp_r_spinbox.blockSignals(True)
                widget.wp_x_spinbox.setValue(new_work_position[0])
                widget.wp_y_spinbox.setValue(new_work_position[1])
                widget.wp_z_spinbox.setValue(new_work_position[2])
                widget.wp_r_spinbox.setValue(new_work_position[3])
                widget.wp_x_spinbox.blockSignals(False)
                widget.wp_y_spinbox.blockSignals(False)
                widget.wp_z_spinbox.blockSignals(False)
                widget.wp_r_spinbox.blockSignals(False)

        else:
            new_work_position = [widget.wp_x_spinbox.value(),
                                 widget.wp_y_spinbox.value(),
                                 widget.wp_z_spinbox.value(),
                                 widget.wp_r_spinbox.value()
                                ]
            self.process_handler.set_step_wp_to(process_step, new_work_position)

    def go_to_step_wp(self, process_step):
        self.process_handler.go_to_step_wp(process_step)

    def set_step_nc_file(self, process_step, widget, browse_file=True):
        """
        Set the NC file for a process step based on UI input.
        :param process_step: handle to the process step of type ProcessStep.
        :param widget: handle to the gui widget in the list.
        :param file_path: Path to the NC file (optional).
        """
        
        if browse_file:
            file_path, _ = QFileDialog.getOpenFileName(
            parent=widget,
            caption="Select a file for this step",
            directory="",
            filter="NC Files (*.nc *.jcode);;All Files (*)"
        )
            if file_path is None:
                return
            self.process_handler.set_step_nc_file(process_step, file_path)
            widget.filename_edit.blockSignals(True)
            widget.filename_edit.setText(file_path)
            widget.filename_edit.blockSignals(False)
        else:
            file_path=widget.filename_edit.currentText()
            self.process_handler.set_step_nc_file(process_step, file_path)
        
        if file_path is not None:
            self.process_handler.recalc_process_params()
    
    def set_rot_motor_id(self, process_step, widget):
        motor_string = widget.rot_mot_combobox.currentText()
        m = re.match(r'^\s*RotMot\s+(-?\d+)\s*$', motor_string)
        if not m:
            motor_id = None
        else:
            try:
                motor_id = int(m.group(1))
            except ValueError:
                motor_id = None
        process_step.rot_motor_id = motor_id

        if motor_id is not None:
            widget.wp_r_spinbox.setEnabled(True)
            #set current rot motor pos as work pos
            current_pos_deg = self.process_handler.rot_motor_controller.read_pos_deg(motor_id)
            widget.wp_r_spinbox.setValue(current_pos_deg)
            
            #position tracking RotMotor
            position_emitter = SignalEmitter()

            def update_pos_threadsave(position):
                position_emitter.float_signal.emit(position)

            def update_current_position(position):
                widget.rel_r_spinbox.setValue(position - process_step.work_position[3])

            position_emitter.float_signal.connect(update_current_position)
            motor = self.process_handler.rot_motor_controller.get_motor_by_id(motor_id)
            motor.set_position_changed_callback(update_pos_threadsave)
        else:
            widget.wp_r_spinbox.setEnabled(False)
            widget.wp_r_spinbox.setValue(0)
            process_step.work_position[3]=0  #reset rot pos in wp

    
    def set_available_rot_motors(self, widgets_list=None):
        """
        Update the available rotational motors in the combobox of each process step.
        :param motor_list: List of available rotational motor objects.
        """
        
        if widgets_list is None: #update all widgets
            widgets_list = []
            for i in range(self.process_steps_listWidget.count()):
                widgets_list.append(self.process_steps_listWidget.itemWidget(self.process_steps_listWidget.item(i)))

        motor_list = self.process_handler.rot_motor_controller.motors

        for widget in widgets_list:
            widget.rot_mot_combobox.clear()
            widget.rot_mot_combobox.addItem("None")
            for motor in motor_list:
                widget.rot_mot_combobox.addItem(f"RotMot {motor.ID}")
            widget.rot_mot_combobox.setCurrentIndex(0)  # set to None by default

    def toggle_process(self):
        state =self.process_handler.process_state
        if state=="Idle":
            self.process_handler.start_process()
            # icon = QIcon("GUI_files/resources/pause.png")
            # self.toggle_process_button.setIcon(icon)
        elif state == "Running":
            self.process_handler.pause_process()
            # icon = QIcon("GUI_files/resources/start.png")
            # self.toggle_process_button.setIcon(icon)
        elif state == "Paused":
            self.process_handler.resume_process()
            # icon = QIcon("GUI_files/resources/pause.png")
            # self.toggle_process_button.setIcon(icon)
    
    def cancel_process(self):
        self.process_handler.cancel_process()
        # icon = QIcon("GUI_files/resources/start.png")
        # self.toggle_process_button.setIcon(icon)
    

    def update_process_state(self, state):
        if state == "Running":
            icon = QIcon("GUI_files/resources/pause.png")
            self.toggle_process_button.setIcon(icon)
            self.cancel_process_button.setEnabled(True)
        elif state == "Paused":
            pass
            icon = QIcon("GUI_files/resources/start.png")
            self.toggle_process_button.setIcon(icon)
            self.cancel_process_button.setEnabled(True)
        elif state == "Idle":
            pass
            icon = QIcon("GUI_files/resources/start.png")
            self.toggle_process_button.setIcon(icon)
            self.cancel_process_button.setEnabled(False)

    def run_bounding_box(self):
        step_to_run = self.bounding_box_step_combobox.currentIndex()
        
        in_laser_coord=False
        if self.gui.bounding_box_mode_combobox.currentText()=="Laser":
            in_laser_coord=True

        if step_to_run is None or step_to_run < 0:
            return
        elif step_to_run == 0:
            for idx,steps in enumerate(self.process_handler.process_step_list):
                self.process_handler.run_bounding_box(idx, in_laser_coord)
        else:
            self.process_handler.run_bounding_box(step_to_run-1, in_laser_coord)
        
