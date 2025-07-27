from PyQt6 import uic
from PyQt6.QtWidgets import QListWidgetItem, QFileDialog
from BaseClasses import BaseClass, TextLogger
import datetime

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
        self.startProcess_button=gui.startProcess_button
        self.startProcess_button.clicked.connect(self.start_process)

        self.cancelProcess_button=gui.cancelProcess_button
        self.cancelProcess_button.clicked.connect(self.cancel_process)

        self.togglePauseProcess_button=gui.togglePauseProcess_button
        self.togglePauseProcess_button.clicked.connect(self.toggle_process_pause)

        #Log tracking
        self.log_textEdit=gui.log_textEdit
        logger = TextLogger(log_object="Process", log_widget=self.log_textEdit)
        self.process_handler.set_log_callback(logger.log)

        #update UI
        self.process_state_edit = gui.process_state_edit
        process_logger = logger = TextLogger(log_object="Process", log_widget=self.process_state_edit, add_stamp=False)
        self.process_handler.set_process_state_callback(process_logger.log)
        self.process_handler.set_process_state_callback(self.update_process_state)

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
        
        widget.remove_button.clicked.connect(lambda _, s=step, w=widget: self.remove_process_step(s,w))
        widget.load_file_button.clicked.connect(lambda _, s=step, w=widget: self.set_step_nc_file(s,w))
        widget.step_name_edit.setText(f"Process Step {len(self.process_handler.process_step_list)}")
        widget.set_current_pos_button.clicked.connect(lambda _, s=step, w=widget, b=True: self.set_step_wp(s,w,b))

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
                widget.wp_x_spinbox.setValue(new_work_position[0])
                widget.wp_y_spinbox.setValue(new_work_position[1])
                widget.wp_z_spinbox.setValue(new_work_position[2])
        else:
            new_work_position = [widget.wp_x_spinbox.Value(),
                                 widget.wp_y_spinbox.Value(),
                                 widget.wp_z_spinbox.Value(),
                                ]
            self.process_handler.set_step_wp_to(process_step, new_work_position)

    
    def set_step_nc_file(self, process_step, widget, file_path=None):
        """
        Set the NC file for a process step based on UI input.
        :param process_step: handle to the process step of type ProcessStep.
        :param widget: handle to the gui widget in the list.
        :param file_path: Path to the NC file (optional).
        """
        
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(
            parent=widget,
            caption="Select a file for this step",
            directory="",
            filter="NC Files (*.nc)"
        )
        if file_path is None:
            return
        else:
            self.process_handler.set_step_nc_file(process_step, file_path)
            widget.filename_edit.setText(file_path)

    def start_process(self):
        # workposition_check = ProcessStartHandler(self.artisan_controller).check_work_position()
        # if workposition_check is None:
        #     self.append_log("Process cancelled by user.")
        #     return
        # else:
        #     self.append_log(workposition_check)
        self.process_handler.start_process()
        # self.togglePauseProcess_button.setChecked(False)
        # self.togglePauseProcess_button.setText("Pause Process")
    
    def cancel_process(self):
        self.process_handler.cancel_process()
        # self.togglePauseProcess_button.setChecked(False)
        # self.togglePauseProcess_button.setText("Pause Process")
    
    def toggle_process_pause(self):
        # if self.togglePauseProcess_button.isChecked():
        #     self.artisan_controller.pause_process()
        #     self.togglePauseProcess_button.setText("Resume Process")
        # else:
        #     self.artisan_controller.resume_process()
        #     self.togglePauseProcess_button.setText("Pause Process")
        self.process_handler.pause_process()
    
    def update_process_state(self, state):
        if state == "Running":
            self.startProcess_button.setEnabled(False)
            self.cancelProcess_button.setEnabled(True)
            self.togglePauseProcess_button.setEnabled(True)
        elif state == "Paused":
            self.startProcess_button.setEnabled(False)
            self.cancelProcess_button.setEnabled(True)
            self.togglePauseProcess_button.setEnabled(True)
        else:
            self.startProcess_button.setEnabled(True)
            self.cancelProcess_button.setEnabled(False)
            self.togglePauseProcess_button.setEnabled(False)
        
