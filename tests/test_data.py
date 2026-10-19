import numpy as np
import pytest
from asammdf import MDF, Signal

from mdf_viewer.data import MDFDataManager


def test_lazy_discovery_identity_and_independent_timestamps(manager, examples):
    channels = manager.open(examples / "edge_cases.mf4")
    assert len(channels) == 5
    assert not manager.cache
    duplicates = [channel for channel in channels if channel.name == "Temperature"]
    assert len(duplicates) == 2
    assert duplicates[0].key != duplicates[1].key
    assert {channel.unit for channel in duplicates} == {"degC", "K"}
    first, second = [manager.load(channel.key) for channel in duplicates]
    np.testing.assert_array_equal(first.timestamps, [0, .02, .08, .11, .4, .9, 1.7, 2.1, 3])
    assert len(second.timestamps) == 31
    assert first.invalid_count == 1
    assert first.nearest(.085) == (.08, 22)
    assert np.isnan(first.nearest(.105)[1])
    assert manager.load(duplicates[0].key) is first
    assert not first.samples.flags.writeable


def test_invalidation_empty_and_unsupported(manager, examples):
    channels = manager.open(examples / "edge_cases.mf4")
    by_name = {channel.name: channel for channel in channels}
    voltage = manager.load(by_name["Sensor Voltage"].key)
    assert voltage.invalid_count == 4
    assert np.isnan(voltage.nearest(1.2)[1])
    empty = manager.load(by_name["Empty Sensor"].key)
    assert empty.nearest(0) is None
    with pytest.raises(ValueError, match="scalar numeric"):
        manager.load(by_name["Text State"].key)


def test_bad_replacement_preserves_recording_and_valid_switch_clears_cache(manager, examples, tmp_path):
    channels = manager.open(examples / "motor_drive.mf4")
    cached = manager.load(channels[0].key)
    bad = tmp_path / "corrupt.mf4"
    bad.write_bytes(b"not an MDF recording")
    with pytest.raises(Exception):
        manager.open(bad)
    assert manager.load(channels[0].key) is cached
    assert manager.open(examples / "empty_recording.mf4") == []
    assert not manager.cache
    assert manager.cache_size == 0


def test_cache_is_bounded_and_evicts_oldest(examples):
    manager = MDFDataManager(cache_bytes=160000)
    try:
        channels = manager.open(examples / "motor_drive.mf4")
        keys = [channel.key for channel in channels[:3]]
        for key in keys:
            manager.load(key)
        assert manager.cache_size <= manager.cache_limit
        assert keys[0] not in manager.cache
        assert keys[-1] in manager.cache
    finally:
        manager.close()


def test_nonmonotonic_duplicate_and_nonfinite_timestamps(manager, tmp_path):
    path = tmp_path / "unusual.mf4"
    with MDF(version="4.10") as mdf:
        mdf.append([Signal(np.array([30., 10., 11., 99.]), np.array([.3, .1, .1, np.nan]), name="Unusual")])
        mdf.save(path, overwrite=True)
    channels = manager.open(path)
    data = manager.load(channels[0].key)
    np.testing.assert_array_equal(data.timestamps, [.1, .1, .3])
    np.testing.assert_array_equal(data.samples, [10, 11, 30])
    assert len(data.notes) == 2
