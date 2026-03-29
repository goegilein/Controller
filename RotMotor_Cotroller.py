from PyQt6 import QtWidgets, QtCore
from Settings_Manager import SettingsManager
from libraries.scservo_sdk import * 
import threading
import numpy as np
import time


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
        self.driver = None

        self._last_log = ''
        self.lock = threading.Lock()



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
                
                #set the driver
                if self.series == "SC" and scscl:
                    self.driver = scscl(self.portHandler)
                if self.series in ("ST", "STS") and sms_sts:
                    self.driver = sms_sts(self.portHandler)

                motor_ids = []
                self.motors = []
                for id in range(1, 10):
                    if self.ping(id):
                        pos = self.read_pos(id)
                        motor = RotMotor(ID=id, raw_position=pos)
                        self.motors.append(motor)
                        motor_ids.append(id)

                        #now set the motor to WHEEL MODE
                        self.driver.unLockEprom(id)
                        self.driver.WheelMode(id)
                        self.driver.LockEprom(id)
                        self.driver.EnableTorque(id, 1)
                self.connected = True

                self.start_control_loop()
                #once connected, constantly track the motor position in a background thread
                # def track_motor_pos():
                #     try:
                #         while self.connected:
                #             time.sleep(0.1)
                #             for motor in self.motors:
                #                 pos = self.read_pos(motor.ID)
                #                 motor.position = pos
                #     except Exception as e:
                #         self.last_log = f"Error in tracking Rotary motor position: {e}."

                # tracking_thread = threading.Thread(target=track_motor_pos)
                # tracking_thread.daemon = True
                # tracking_thread.start()

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
    
    def start_control_loop(self):
        """Starts thread for position tracking and control"""
        def control_thread_func():
            while self.connected:
                with self.lock: # Thread safety if GUI also writes
                    for motor in self.motors:
                        try:
                            # 1. Read position (actual value)
                            # Optimization: ReadPos returns position
                            current_raw = self.read_pos(motor.ID)
                            
                            # if res == COMM_SUCCESS:
                            # 2. Update motor status (calculates turns & total ticks)
                            motor.update_from_raw(current_raw)
                            
                            # 3. Calculate PID speed
                            speed_cmd = motor.calculate_control_speed()
                                
                            self.driver.WriteSpec(motor.ID, speed_cmd, motor.acc)
                                
                        except Exception as e:
                            print(f"Error control loop ID {motor.ID}: {e}")

                # Loop-Frequency: 20ms = 50Hz (Important for PID!)
                time.sleep(0.02) 

        t = threading.Thread(target=control_thread_func)
        t.daemon = True
        t.start()

    #--- Core Motor Control Methods ----

    def move_to_angle(self, sid, angle, wait_for_position = False):
        """Sets new target (also > 360 degrees)"""
        # If sid is -1, move all motors
        motors = self.get_motor_by_id(sid)

        with self.lock:
            for m in motors:
                m.set_target_angle(angle)
                # Background thread now handles movement automatically
        if wait_for_position:
            time.sleep(0.1) #give some time for the command to be sent
            for m in motors:
                while not m.position_reached:
                    time.sleep(0.1)
    
    def set_acc(self, sid, acc: int):
        """Sets acceleration for a specific motor"""
        # If sid is -1, move all motors
        motors = self.get_motor_by_id(sid)

        with self.lock:
            for m in motors:
                m.acc = acc
    
    def set_speed(self, sid, speed: int):
        """Sets speed for a specific motor"""
        # If sid is -1, move all motors
        motors = self.get_motor_by_id(sid)

        with self.lock:
            for m in motors:
                m.speed_limit = speed
    
    def stop_motor(self, sid):
        """Stops a specific motor immediately"""
        # If sid is -1, move all motors
        motors = self.get_motor_by_id(sid)

        with self.lock:
            for m in motors:
                self.driver.WriteSpec(m.ID, 0, m.acc)
                m.position_reached = True
    
    def get_current_angle(self, sid):
        """Gets current angle in degrees (also > 360 degrees)"""
        motors = self.get_motor_by_id(sid)

        if motors:
            pos = [m.get_current_angle() for m in motors]
            return pos
        return None
    


    # ---- Core helpers for Motor Controls
    def ping(self, sid: int) -> bool:
        if sid is None:
            return False
        
        scs_model_number, scs_comm_result, scs_error = self.driver.ping(sid)
        return scs_comm_result == COMM_SUCCESS


    def torque(self, sid: int, on: bool = True):
        if sid is None:
            return
        elif sid == -1: # all motors
            ids = self.get_motor_ids()
        else: 
            ids = [sid]
        
        for id in ids:
                self.driver.EnableTorque(id, 1 if on else 0)
                return

    def read_pos(self, sid: int) -> int:
        if sid is None:
            return
        
        return self.driver.ReadPos(sid)[0]

    
    def is_connection_active(self) -> bool:
        return self.connected and self.portHandler is not None

    def get_motor_by_id(self, sid: int):
        # -1 means all motors
        if sid is None:
            return None
        else:
            motors = self.motors if sid == -1 else [m for m in self.motors if m.ID == sid]
            return motors
    
    def get_motor_ids(self):
        if not self.motors:
            return []
        return [motor.ID for motor in self.motors]
    

class RotMotor:
    def __init__(self, ID, raw_position=0, speed=1000, acc=50):
        self.ID = ID
        
        # --- Multi-turn tracking ---
        self.last_raw_pos = raw_position
        self.turn_count = 0
        self.total_ticks = raw_position
        
        # --- Target values ---
        self.target_ticks = raw_position
        self.speed_limit = speed
        self.acc = acc
        self.gear_ratio = 3  # Gear ratio (1.0 = direct drive)
        
        # --- PID parameters (tuning required) ---
        self.Kp = 1.5   # Proportional: "Motor force: 1.5 default"
        self.Ki = 0.5  # Integral: "Work against load: 0.05 default"
        self.Kd = 1   # Derivative: "Brake / damping: 0.8 default"
        
        # --- PID state ---
        self.integral_error = 0.0
        self.last_error = 0.0
        self.last_update_time = time.time()

        #track position state
        self.position_reached = True
        self.position_reached_time = time.time()
        self.position_reached_timeout = 100 #seconds
        self.position_stable_counter = 0
        self.position_stable_threshold = 5 #number of cycles position must be stable to consider reached
        
        # Callbacks
        self.position_changed_callback = []

    def update_from_raw(self, new_raw_pos):
        """Calculates overflows and absolute position."""
        diff = new_raw_pos - self.last_raw_pos
        
        # Wrap-around detection (4096 ticks per revolution)
        if diff < -2048:
            self.turn_count += 1
        elif diff > 2048:
            self.turn_count -= 1
            
        self.last_raw_pos = new_raw_pos
        self.total_ticks = (self.turn_count * 4096) + new_raw_pos
        
        if self.position_changed_callback:
            # Convert to degrees for GUI
            deg = round((self.total_ticks / 4096.0) * 360.0 / self.gear_ratio, 2)
            for callback in self.position_changed_callback:
                callback(deg)

    def set_target_angle(self, angle):
        """
        Sets new target angle.
        Resets PID values to avoid jumps.
        """
        new_target = int((angle / 360.0) * 4096.0 * self.gear_ratio)
        
        if new_target != self.target_ticks:
            self.target_ticks = new_target
            
            # Reset integral (prevents windup from previous movement)
            self.integral_error = 0.0
            
            # Reset last error (prevents "derivative kick")
            # We pretend the error just occurred,
            # so the D-term doesn't immediately counter-steer hard.
            self.last_error = new_target - self.total_ticks
            
            self.last_update_time = time.time()
    
    def get_target_angle(self):
        """Returns the target angle in degrees."""
        return round((self.target_ticks / 4096.0) * 360.0 / self.gear_ratio, 2)
    
    def get_current_angle(self):
        """Returns the current angle in degrees."""
        return round((self.total_ticks / 4096.0) * 360.0 / self.gear_ratio, 2)
    
    def set_speed(self, speed):
        self.speed_limit = speed
    
    def set_acc(self, acc):
        self.acc = acc

    def calculate_control_speed(self):
        """
        Full PID controller.
        Returns: Speed (-1000 to 1000)
        """
        now = time.time()
        dt = now - self.last_update_time
        
        # Protection against division by zero or huge pauses
        if dt <= 0.0001: dt = 0.001
        if dt > 0.5: dt = 0.1 # Cap on lag
        
        self.last_update_time = now

        # 1. Calculate error
        error = self.target_ticks - self.total_ticks
        
        # Deadband (tolerance): If close enough, stop.
        # 10 ticks ~ 0.8 degrees
        if abs(error) < 3: 
            self.integral_error = 0 # Clear integral
            self.last_error = 0
            self.position_stable_counter +=1
            if self.position_stable_counter >= self.position_stable_threshold and self.position_reached== False:
                self.position_reached = True
            return 0
        else:
            self.position_stable_counter = 0
            self.position_reached = False

        # 2. Proportional (P)
        p_term = self.Kp * error

        # 3. Integral (I) with anti-windup
        self.integral_error += error * dt
        
        # Limit I-term (e.g., to +/- 400 speed units)
        # Prevents I-term from becoming too powerful.
        max_i = 400 
        i_contrib = self.Ki * self.integral_error
        
        if i_contrib > max_i:
            self.integral_error = max_i / self.Ki
            i_contrib = max_i
        elif i_contrib < -max_i:
            self.integral_error = -max_i / self.Ki
            i_contrib = -max_i
        
        i_term = i_contrib

        # 4. Derivative (D)
        # Change of error over time
        # (error - last_error) / dt
        delta_error = error - self.last_error
        d_term = self.Kd * (delta_error / dt)
        
        self.last_error = error

        # 5. Sum (output)
        output_speed = p_term + i_term + d_term
        
        # 6. Limit to hardware & user settings
        limit = min(self.speed_limit, 1000) # Hardware max is 1000
        
        if output_speed > limit: output_speed = limit
        if output_speed < -limit: output_speed = -limit
        
        # Cast to int for protocol
        output_speed = int(output_speed)

        # 7. Minimum power (stiction)
        # Prevents values in range -20 to 20 where motor only hums
        min_pwr = 30
        if 0 < output_speed < min_pwr: output_speed = min_pwr
        if -min_pwr < output_speed < 0: output_speed = -min_pwr
            
        return output_speed
    
    def set_position_changed_callback(self, callback):
        self.position_changed_callback.append(callback)

        


