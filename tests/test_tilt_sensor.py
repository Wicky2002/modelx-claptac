import math
import sys
import types

import pytest

from hardware.pi import sensors
from hardware.pi.sensors import build_sensor, tilt_degrees


def test_tilt_is_the_angle_between_gravity_directions():
    assert tilt_degrees([0, 0, 1], [0, 0, 5]) == pytest.approx(0.0)
    assert tilt_degrees([0, 0, 1], [0, 1, 0]) == pytest.approx(90.0)
    lean = math.radians(3)
    assert tilt_degrees([0, 0, 16384], [0, math.sin(lean), math.cos(lean)]) == pytest.approx(3.0)
    with pytest.raises(ValueError):
        tilt_degrees([0, 0, 0], [0, 0, 1])


class FakeBus:
    def __init__(self, bus):
        self.vector = (0, 0, 16384)

    def write_byte_data(self, *args):
        pass

    def read_i2c_block_data(self, address, register, length):
        out = []
        for v in self.vector:
            v &= 0xFFFF
            out += [v >> 8, v & 0xFF]
        return out


def test_driver_reports_degrees_from_the_installed_angle(monkeypatch):
    monkeypatch.setitem(sys.modules, "smbus2", types.SimpleNamespace(SMBus=FakeBus))
    monkeypatch.setattr(sensors.time, "sleep", lambda s: None)
    sensor = build_sensor({"driver": "mpu6050_tilt", "sensor_id": "tilt-01", "samples": 2})
    assert sensor.read()[0].value == pytest.approx(0.0)
    lean = math.radians(5)
    sensor._bus.vector = (0, int(-16384 * math.sin(lean)), int(16384 * math.cos(lean)))
    reading = sensor.read()[0]
    assert (reading.type, reading.unit) == ("tilt", "deg")
    assert reading.value == pytest.approx(5.0, abs=0.05)
