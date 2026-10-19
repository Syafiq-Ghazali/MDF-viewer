"""Generate synthetic, redistributable MDF4 recordings; no hardware required."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from asammdf import MDF, Signal
import numpy as np


def recording():
    mdf = MDF(version="4.10")
    mdf.header.start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return mdf


def generate(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    with recording() as mdf:
        t = np.arange(0, 5, 0.001)
        mdf.append([
            Signal(48 + 0.5 * np.sin(2 * np.pi * 6 * t) - 4 * ((t > 2.5) & (t < 2.7)), t,
                   name="DC Bus Voltage", unit="V", comment="Synthetic DC bus with a load transient at 2.5 s"),
            Signal(np.full_like(t, 48), t, name="DC Bus Reference", unit="V", comment="Nominal DC link target"),
            *[Signal(10 * np.sin(2 * np.pi * 20 * t + phase), t, name=f"Phase {name} Current", unit="A",
                     comment="Synthetic three-phase current")
              for name, phase in zip("ABC", (0, -2 * np.pi / 3, 2 * np.pi / 3))],
        ], common_timebase=True)
        slow = np.arange(0, 5, 0.01)
        mdf.append([Signal(0.5 + 0.12 * np.sin(2 * np.pi * slow), slow, name="Duty Cycle", unit="",
                           comment="100 Hz control sample rate; current/voltage group uses 1 kHz")])
        mdf.save(destination / "motor_drive.mf4", overwrite=True)

    with recording() as mdf:
        t = np.array([0, 0.02, 0.08, 0.11, 0.4, 0.9, 1.7, 2.1, 3.0])
        mdf.append([Signal(np.array([20, 21, 22, np.nan, 25, 26, 24, 23, 22]), t,
                           name="Temperature", unit="degC", comment="Irregular timestamps; NaN at 0.11 s")])
        other = np.arange(0, 3.1, 0.1)
        mdf.append([Signal(293 + 2 * np.sin(other), other, name="Temperature", unit="K",
                           comment="Duplicate channel name in a separate group; different unit and timebase")])
        invalid = np.zeros(len(other), dtype=bool)
        invalid[12:16] = True
        mdf.append([Signal(5 + np.cos(other), other, name="Sensor Voltage", unit="V",
                           invalidation_bits=invalid, comment="Four samples flagged invalid by MDF4 invalidation bits")])
        mdf.append([Signal(np.array([], dtype=float), np.array([], dtype=float), name="Empty Sensor", unit="A",
                           comment="No samples recorded; should display safely")])
        mdf.append([Signal(np.array([b"idle", b"run", b"stop"], dtype="S4"), np.array([0., 1., 2.]),
                           name="Text State", encoding="utf-8",
                           comment="Text channel: intentionally unsupported for numeric plotting")])
        mdf.save(destination / "edge_cases.mf4", overwrite=True)

    with recording() as mdf:
        mdf.save(destination / "empty_recording.mf4", overwrite=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "examples")
    generate(parser.parse_args().output)
