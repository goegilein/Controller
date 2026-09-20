import unittest

from Process_Handler import ProcessHandler, ProcessStep


class DummyController:
    def __init__(self):
        self.connected = True
        self.laser_offset = [0, 0, 0]
        self.abs_position = [0, 0, 0]
        self.last_log = ""

    def get_absolute_position(self):
        return [0, 0, 0]

    def move_axis_absolute(self, *args, **kwargs):
        return None

    def move_axis_to(self, *args, **kwargs):
        return None

    def set_work_position(self, *args, **kwargs):
        return None

    def send_command(self, command):
        return None

    def add_sync_position(self, *args, **kwargs):
        return None


class DummyRotMotorController:
    def move_to_angle(self, *args, **kwargs):
        return None


class DummyGui:
    pass


class ProcessHandlerRemainingTimeTests(unittest.TestCase):
    def test_process_remaining_time_resets_to_zero_after_completion(self):
        controller = DummyController()
        handler = ProcessHandler(DummyGui(), controller, DummyRotMotorController())

        step = ProcessStep([0, 0, 0, 0], name="Demo Step")
        step.command_lists = [["G1 X1", "G1 X2"]]
        step.time_lists = [[2.0, 3.0]]
        step.jcode_command_list = ["J1 0"]
        step.process_time = 5.0
        step.nc_file = "dummy.nc"
        step.file_type = "gcode"
        handler.process_step_list = [step]

        handler.start_process()
        if handler.execution_thread is not None:
            handler.execution_thread.join(timeout=2)

        self.assertEqual(handler.remaining_time, 0)

    def test_process_remaining_time_starts_from_total_runtime(self):
        controller = DummyController()
        handler = ProcessHandler(DummyGui(), controller, DummyRotMotorController())

        step = ProcessStep([0, 0, 0, 0], name="Demo Step")
        step.command_lists = [["G1 X1", "G1 X2"]]
        step.time_lists = [[1.5, 3.5]]
        step.jcode_command_list = ["J1 0"]
        step.process_time = 5.0
        step.nc_file = "dummy.nc"
        step.file_type = "gcode"
        handler.process_step_list = [step]

        handler.recalc_process_params()

        self.assertEqual(handler.remaining_time, 5.0)


if __name__ == "__main__":
    unittest.main()
