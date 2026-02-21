from PyQt6.QtWidgets import QWidget, QVBoxLayout
from BaseClasses import BaseClass, SignalEmitter, TextLogger
import RotMotor_Cotroller
from PyQt6 import uic
from PathManager import get_gui_file_path

class RotMotorInterface(BaseClass):
    def __init__(self, gui, rot_motor_controller: RotMotor_Cotroller.RotMotorCotroller):
        super().__init__()
        self.gui = gui
        self.rot_mot_controller = rot_motor_controller
        self.widget_path = str(get_gui_file_path("rot_motor_widget.ui"))
        self.update_connection_status(self.rot_mot_controller.connected)

        #Log tracking
        self.log_textEdit=gui.log_textEdit
        logger = TextLogger(log_object="RotMot", log_widget=self.log_textEdit)
        self.rot_mot_controller.set_log_callback(logger.log)

        #Connection status tracking
        self.rot_mot_controller.set_connected_callback(self.update_connection_status)
        
    

    def update_connection_status(self, connected: bool):
        if connected:
            self.build_gui()
        else:
            self.delete_gui()
        

    def build_gui(self):
        motors = self.rot_mot_controller.motors
        tab_widget = self.gui.rot_mot_tabWidget
        if not motors:
            return
        for tab in range(tab_widget.count()-1, -1, -1):
            tab_widget.removeTab(tab)

        for idx, motor in enumerate(motors):

            # 1) Create an empty tab container
            tab = QWidget()

            # 2) Layout for the tab
            layout = QVBoxLayout(tab)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(8)

            widget = uic.loadUi(self.widget_path)
            self.connect_widget_callbacks(widget, motor)

            layout.addWidget(widget)
            tab.setLayout(layout)

            tab_widget.addTab(tab, f"RotMot {motor.ID}")
    
    def delete_gui(self):
        tab_widget = self.gui.rot_mot_tabWidget
        for tab in range(tab_widget.count()-1, -1, -1):
            tab_widget.removeTab(tab)

    def connect_widget_callbacks(self, widget, motor):
        id= motor.ID

        #set start values
        widget.speed_spinbox.setValue(motor.speed_limit)
        widget.acc_spinbox.setValue(motor.acc)
        widget.target_pos_spinbox.setValue(motor.get_target_angle())
        
        # widget.move_button.clicked.connect(lambda _, i=id, b=blocking: self.rot_mot_controller.move_motor_to_target(i,b))
        widget.move_button.clicked.connect(lambda _, i = id, w=widget,  b=False: self.rot_mot_controller.move_to_angle(sid=i, angle=w.target_pos_spinbox.value(), wait_for_position=b))
        # widget.target_pos_spinbox.valueChanged.connect(lambda _, i=id, w=widget: self.rot_mot_controller.set_target_position_deg(i, w.target_pos_spinbox.value()))
        # widget.target_pos_spinbox.valueChanged.connect(lambda _, w=widget: motor.set_target_angle(w.target_pos_spinbox.value()))
        widget.speed_spinbox.valueChanged.connect(lambda _, i=id, w=widget: self.rot_mot_controller.set_speed(sid=i, speed=w.speed_spinbox.value()))
        widget.acc_spinbox.valueChanged.connect(lambda _, i=id, w=widget: self.rot_mot_controller.set_acc(sid=i, acc=w.acc_spinbox.value()))
        widget.move_to_home_button.clicked.connect(lambda _, i=id, w=widget, b=False: self.rot_mot_controller.move_to_angle(sid=i, angle=w.home_pos_spinbox.value(), wait_for_position=b))
        
        #set work position
        def set_work_pos():
            home_pos = motor.get_current_angle()
            widget.home_pos_spinbox.blockSignals(True)
            widget.home_pos_spinbox.setValue(home_pos)
            widget.home_pos_spinbox.blockSignals(False)

        widget.set_home_button.clicked.connect(set_work_pos)

        #move by steps
        def move_by_steps(dir):
            # current_pos = self.rot_mot_controller.read_pos_deg(id)
            # target_pos = current_pos + widget.step_size_spinbox.value()*dir
            delta = widget.step_size_spinbox.value()*dir
            widget.target_pos_spinbox.blockSignals(True)
            widget.target_pos_spinbox.setValue(widget.target_pos_spinbox.value() + delta)
            widget.target_pos_spinbox.blockSignals(False)
            # self.rot_mot_controller.set_target_position_deg(id, target_pos)
            self.rot_mot_controller.move_to_angle(sid=id, angle=widget.target_pos_spinbox.value(), wait_for_position=False)
        
        widget.pos_step_button.clicked.connect(lambda _, d=1: move_by_steps(d))
        widget.neg_step_button.clicked.connect(lambda _, d=-1: move_by_steps(d))

        #position tracking
        self.position_emitter = SignalEmitter()

        def update_pos_threadsave(position):
            self.position_emitter.float_signal.emit(position)

        def update_current_position(position):
            widget.current_pos_spinbox.blockSignals(True)
            widget.home_pos_spinbox.blockSignals(True)
            widget.current_pos_spinbox.setValue(position)
            widget.rel_pos_spinbox.setValue(position-widget.home_pos_spinbox.value())
            widget.current_pos_spinbox.blockSignals(False)
            widget.home_pos_spinbox.blockSignals(False)

        self.position_emitter.float_signal.connect(update_current_position)
        motor.set_position_changed_callback(update_pos_threadsave)




    