from PyQt6 import QtWidgets, QtCore
from Settings_Manager import SettingsManager
from libraries.scservo_sdk import * 
import threading


class RotMotorCotroller:
    """
    Thin wrapper that adapts SC vs ST/STS differences into a common interface.
    """
    def __init__(self, settings: SettingsManager):

        self.s = settings
        self.portHandler = None
        self.load_settings()
        settings.settingChanged.connect(self.load_settings) #reload settings if they change
        settings.settingsReplaced.connect(self.load_settings)
        self.motors = [] # type: list[RotMotor]
        self._connected = False

        self._last_log = ''


        #callback
        self.log_callbacks = []
        self.connected_callbacks = []
    
    @property
    def last_log(self):
        return self._last_log
    
    @last_log.setter
    def last_log(self, value):
        self._last_log = value
        if self.log_callbacks:#
            for callback in self.log_callbacks:
                callback(value)

    def set_log_callback(self, callback):
        self.log_callbacks.append(callback)

    @property
    def connected(self):
        return self._connected
    
    @connected.setter
    def connected(self, value):
        self._connected = value
        if self.connected_callbacks:
            for callback in self.connected_callbacks:
                callback(value)
    
    def set_connected_callback(self, callback):
        self.connected_callbacks.append(callback)

    def connect(self):
        if not self.connected and self.portHandler is None:
            try:
                self.portHandler = PortHandler(self.port)
                if self.portHandler.openPort():
                    self.last_log = f"Rot Motor Board connected on {self.port}"

                motor_ids = []
                self.motors = []
                for ids in range(1, 255):
                    if self.ping(ids):
                        pos = self.read_pos(ids)
                        motor = RotMotor(ID=ids, position=pos)
                        self.motors.append(motor)
                        motor_ids.append(ids)
                self.connected = True

                #once connected, constantly track the motor position in a background thread
                def track_motor_pos():
                    try:
                        while self.connected:
                            time.sleep(0.1)
                            for motor in self.motors:
                                pos = self.read_pos(motor.ID)
                                motor.position = pos
                    except Exception as e:
                        self.last_log = f"Error in tracking Rotary motor position: {e}."

                tracking_thread = threading.Thread(target=track_motor_pos)
                tracking_thread.daemon = True
                tracking_thread.start()

                self.last_log = f"Detected motors with IDs: {motor_ids}."
            except Exception as e:
                self.connected = False
                self.portHandler = None
                self.last_log = f"Rotary Motor Board connection error: {e}."
        else:
            self.last_log = "Rotary Motor Board already connected."
          
    def disconnect(self):
        if self.connected:
            try:
                self.motors = []
                self.portHandler.closePort()
                self.portHandler = None
                self.last_log = "Rot Motor Board disconnected."
                self.connected = False
            except Exception as e:
                self.last_log = f"Rotary Motor Board disconnection error: {e}"
        else:
            self.last_log = "No Rotary Motor Board connected."


    def load_settings(self):
        if not self.s:
            return
        self.port = self.s.get("rotary_motors.port", "COM7")
        self.series = self.s.get("rotary_motors.series", "STS")
    
    

    # ---- Core helpers for Motor Controls
    def ping(self, sid: int) -> bool:
        if sid is None:
            return False
        
        if self.series == "SC" and scscl:
            scs_model_number, scs_comm_result, scs_error = scscl(self.portHandler).ping(sid)
            return scs_comm_result == COMM_SUCCESS
        if self.series in ("ST", "STS") and sms_sts:
            scs_model_number, scs_comm_result, scs_error = sms_sts(self.portHandler).ping(sid)
            return scs_comm_result == COMM_SUCCESS
        raise RuntimeError("Selected series module not available")

    def torque(self, sid: int, on: bool = True):
        if sid is None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]
        
        for id in ids:
            if self.series == "SC" and scscl:
                scscl(self.portHandler).EnableTorque(id, 1 if on else 0)
                return
            if self.series in ("ST", "STS") and sms_sts:
                sms_sts(self.portHandler).EnableTorque(id, 1 if on else 0)
                return
            raise RuntimeError("Selected series module not available")
    
    def write_pos(self, sid: int, pos: int, speed: int = 1000, acc: int = 50, blocking: bool=False):
        if sid==None:
            return
        
        if self.series == "SC" and scscl:
            scscl(self.portHandler).WritePos(sid, pos, speed, acc)
            while self.read_moving(sid) and blocking:
                time.sleep(0.1)
            return "Done"
        if self.series in ("ST", "STS") and sms_sts:
            # Many ST/STS SDKs name it WritePosEx
            sms_sts(self.portHandler).WritePosEx(sid, pos, speed, acc)
            while self.read_moving(sid) and blocking:
                time.sleep(0.1)
            return "Done"
        raise RuntimeError("Selected series module not available")

    def move_motor_to_target(self, sid: int, blocking: bool=False, high_resolution: bool=False):
        if sid == None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]
        
        for id in ids:
            motor = self.get_motor_by_id(id)
            pos = motor.target_position
            target_pos_deg = motor.target_position_deg
            speed = motor.speed
            acc = motor.acc

            self.write_pos(id, pos, speed, acc, blocking)
            if high_resolution and blocking:
                #fine tune position
                for i in range(5): #try up to 5 times
                    time.sleep(0.2)
                    current_pos_deg = self.read_pos_deg(sid)
                    delta = target_pos_deg - current_pos_deg
                    if abs(delta) > 0.1: #if more than 0.1 deg off, try doing a fine adjustment
                        sign = 1 if delta > 0 else -1
                        target_pos = motor.convert_degrees_to_position(target_pos_deg + sign*0.3)
                        self.write_pos(sid, target_pos, speed=100, acc=10, blocking=True)
                    else:
                        break
    
    def move_motor_by_deg(self, sid: int = None, delta_deg: float = 0.1, blocking: bool=False):
        if sid is None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]
        
        for id in ids:
            motor = self.get_motor_by_id(id)
            current_pos_deg = self.read_pos_deg(sid)
            target_pos = motor.convert_degrees_to_position(current_pos_deg + delta_deg)
            speed = motor.speed
            acc = motor.acc
            self.write_pos(sid, target_pos, speed, acc, blocking)
            return True
        return False
    
    def move_motor_to_position_deg(self, sid: int, position_deg: float = 0.0, blocking: bool=False, high_resolution: bool=False):
        if sid is None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]
        
        for id in ids:
            motor = self.get_motor_by_id(id)
            target_pos = motor.convert_degrees_to_position(position_deg)
            speed = motor.speed
            acc = motor.acc
            self.write_pos(sid, target_pos, speed, acc, blocking)
            if high_resolution and blocking:
                #fine tune position
                for i in range(5): #try up to 5 times
                    time.sleep(0.2)
                    current_pos_deg = self.read_pos_deg(sid)
                    delta = position_deg - current_pos_deg
                    if abs(delta) > 0.1: #if more than 0.1 deg off, try doing a fine adjustment
                        sign = 1 if delta > 0 else -1
                        target_pos = motor.convert_degrees_to_position(position_deg+ sign*0.3)
                        self.write_pos(sid, target_pos, speed=100, acc=10, blocking=True)
                    else:
                        break
    
    def move_motor_rel_to_wp_deg(self, sid: int, delta_deg: float = 0.0, blocking: bool=False):
        if sid is None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]
        
        for id in ids:
            motor = self.get_motor_by_id(id)
            work_pos_deg = self.get_work_position_deg(id)
            target_pos = motor.convert_degrees_to_position(work_pos_deg + delta_deg)
            speed = motor.speed
            acc = motor.acc
            self.write_pos(id, target_pos, speed, acc, blocking)

    def move_motor_to_wp(self, sid: int):
        if sid is None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]
        
        for id in ids:
            home_pos = self.get_motor_by_id(id).work_position
            speed = self.get_motor_by_id(id).speed
            acc = self.get_motor_by_id(id).acc
            self.write_pos(id, home_pos, speed, acc, blocking=True)

    def read_pos(self, sid: int) -> int:
        if sid is None:
            return
        
        if self.series == "SC" and scscl:
            return scscl(self.portHandler).ReadPos(sid)[0]
        if self.series in ("ST", "STS") and sms_sts:
            return sms_sts(self.portHandler).ReadPos(sid)[0]
        raise RuntimeError("Selected series module not available")
    
    def read_pos_deg(self, sid: int) -> float:
        if sid is None:
            return
        
        motor = self.get_motor_by_id(sid)
        if motor:
            pos = self.read_pos(sid)
            return round((pos / 4095) * 360, 2)
        return None
    
    def read_moving(self, sid: int) -> bool:
        if sid is None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]

        for id in ids:
            if self.series == "SC" and scscl:
                moving, _, _ = scscl(self.portHandler).ReadMoving(id)
                if moving == 1:
                    return True
                else: 
                    time.sleep(0.1)
                    moving, _, _ = scscl(self.portHandler).ReadMoving(id)
                    if moving == 1:
                        return True
            if self.series in ("ST", "STS") and sms_sts:
                moving, _, _ = sms_sts(self.portHandler).ReadMoving(id)
                if moving == 1:
                    return True
                else: 
                    time.sleep(0.1)
                    moving, _, _ = scscl(self.portHandler).ReadMoving(id)
                    if moving == 1:
                        return True
            else:
                return
                raise RuntimeError("Selected series module not available")
        
        return False
    
    def set_speed(self, sid: int, speed: int = 1000):
        if sid is None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]
        
        for id in ids:
            self.get_motor_by_id(id).speed = speed
    
    def get_speed(self, sid: int) -> int:
        if sid is None:
            return
        return self.get_motor_by_id(sid).speed

    def set_acc(self, sid: int, acc: int):
        if sid is None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]
        
        for id in ids:
            self.get_motor_by_id(id).acc = acc
    
    def get_acc(self, sid: int) -> int:
        if sid is None:
            return
        return self.get_motor_by_id(sid).acc
    
    def set_target_position_deg(self, sid: int, position_deg: float):
        if sid is None:
            return
        motor = self.get_motor_by_id(sid)
        if motor:
            motor.target_position_deg = position_deg
            return True
        return False
    
    def get_target_position_deg(self, sid: int) -> float:
        if sid is None:
            return
        motor = self.get_motor_by_id(sid)
        if motor:
            return motor.target_position_deg
        return None
    
    def set_work_position(self, sid: int):
        if sid is None:
            return
        
        motor = self.get_motor_by_id(sid)
        if motor:
            pos = self.read_pos(sid)
            motor.work_position = pos
            return True
        return False
    
    def get_work_position(self, sid: int) -> int:
        if sid is None:
            return
        motor = self.get_motor_by_id(sid)
        if motor:
            return motor.work_position
        return None
    
    def get_work_position_deg(self, sid: int) -> float:
        if sid is None:
            return
        motor = self.get_motor_by_id(sid)
        if motor:
            return motor.convert_position_to_degrees(motor.work_position)
        return None
    
    def is_connection_active(self) -> bool:
        return self.connected and self.portHandler is not None

    def get_motor_by_id(self, ID: int):
        if ID is None:
            return None
        for motor in self.motors:
            if motor.ID == ID:
                return motor
        return None
    
    def get_motor_ids(self):
        if not self.motors:
            return []
        return [motor.ID for motor in self.motors]
    
class RotMotor():
    def __init__(self, ID, position=0, speed=100, acc=5):
        self.ID = ID
        self._position = position
        self._position_deg = self.convert_position_to_degrees(position)
        self._target_position_deg = 0
        self._target_position = self.convert_degrees_to_position(self._target_position_deg)
        self.work_position = position
        self.speed = speed
        self.acc = acc

        self.position_changed_callback = []

    @property
    def position_deg(self):
        return self._position_deg
    
    @property
    def position(self):
        return self._position
    
    @position.setter
    def position(self, value):
        self._position = value
        self._position_deg = self.convert_position_to_degrees(value)
        if self.position_changed_callback:
            for callback in self.position_changed_callback:
                callback(self._position_deg)

    @property
    def target_position(self):
        return self._target_position
    
    @property
    def target_position_deg(self):
        return self._target_position_deg
    
    @target_position_deg.setter
    def target_position_deg(self, value):
        self._target_position_deg = value%360
        self._target_position = self.convert_degrees_to_position(value%360)
    
    def convert_position_to_degrees(self, position):
        # Assuming a linear conversion for demonstration purposes
        return round((position / 4095) * 360, 2)
    
    def convert_degrees_to_position(self, degrees):
        # Assuming a linear conversion for demonstration purposes
        return int((degrees / 360) * 4095)
    
    def set_position_changed_callback(self, callback):
        self.position_changed_callback.append(callback)
    


        


