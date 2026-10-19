"""MDF access and bounded caching. Used exclusively on the file worker thread."""

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import re

from asammdf import MDF
import numpy as np


@dataclass(frozen=True, order=True)
class ChannelKey:
    group: int
    index: int


@dataclass(frozen=True)
class ChannelInfo:
    key: ChannelKey
    name: str
    unit: str
    description: str
    sample_count: int

    @property
    def label(self) -> str:
        unit = f" [{self.unit}]" if self.unit else ""
        return f"{self.name}{unit} (G{self.key.group}:C{self.key.index})"


@dataclass(frozen=True)
class ChannelData:
    info: ChannelInfo
    timestamps: np.ndarray
    samples: np.ndarray
    invalid_count: int
    notes: tuple[str, ...] = ()

    @property
    def nbytes(self) -> int:
        return self.timestamps.nbytes + self.samples.nbytes

    def nearest(self, time: float) -> tuple[float, float] | None:
        """Return a recorded sample, including invalid values; never interpolate."""
        if not len(self.timestamps):
            return None
        right = min(int(np.searchsorted(self.timestamps, time)), len(self.timestamps) - 1)
        left = max(0, right - 1)
        index = left if abs(self.timestamps[left] - time) <= abs(self.timestamps[right] - time) else right
        return float(self.timestamps[index]), float(self.samples[index])


class MDFDataManager:
    def __init__(self, cache_bytes: int = 256 * 1024 * 1024):
        self.cache_limit = cache_bytes
        self.mdf: MDF | None = None
        self.channels: dict[ChannelKey, ChannelInfo] = {}
        self.cache: OrderedDict[ChannelKey, ChannelData] = OrderedDict()
        self.cache_size = 0

    def open(self, path: str | Path) -> list[ChannelInfo]:
        """Keep the current recording intact if opening a replacement fails."""
        candidate = MDF(path)
        try:
            channels = {}
            for group_index, group in enumerate(candidate.groups):
                for index, channel in enumerate(group.channels):
                    # The time master is an axis, not a measurement signal.
                    if candidate.masters_db.get(group_index) == index:
                        continue
                    key = ChannelKey(group_index, index)
                    description = candidate.get_channel_comment(group=group_index, index=index)
                    channels[key] = ChannelInfo(
                        key=key,
                        name=channel.name,
                        unit=candidate.get_channel_unit(group=group_index, index=index),
                        description=re.sub(r"<[^>]+>", " ", description).strip(),
                        sample_count=group.channel_group.cycles_nr,
                    )
        except Exception:
            candidate.close()
            raise
        self.close()
        self.mdf = candidate
        self.channels = channels
        return list(channels.values())

    def load(self, key: ChannelKey) -> ChannelData:
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if self.mdf is None:
            raise ValueError("Open an MDF recording first.")
        info = self.channels[key]
        # Retain invalidated samples at their original timestamps for inspection.
        signal = self.mdf.get(group=key.group, index=key.index, ignore_invalidation_bits=True)
        samples = np.asarray(signal.samples)
        if samples.ndim != 1 or samples.dtype.kind not in "biuf":
            raise ValueError(f"{info.name}: only scalar numeric channels can be plotted.")
        timestamps = np.asarray(signal.timestamps, dtype=np.float64)
        samples = np.array(samples, dtype=np.float64, copy=True)
        invalid = ~np.isfinite(samples)
        if signal.invalidation_bits is not None:
            invalid |= np.asarray(signal.invalidation_bits, dtype=bool)
        samples[invalid] = np.nan
        notes = []
        finite_time = np.isfinite(timestamps)
        if not finite_time.all():
            notes.append(f"Dropped {np.count_nonzero(~finite_time)} non-finite timestamps")
            timestamps, samples = timestamps[finite_time], samples[finite_time]
        if np.any(np.diff(timestamps) < 0):
            notes.append("Samples sorted by recorded timestamp")
            order = np.argsort(timestamps, kind="stable")
            timestamps, samples = timestamps[order], samples[order]
        invalid_count = int(np.count_nonzero(~np.isfinite(samples)))
        timestamps.flags.writeable = False
        samples.flags.writeable = False
        result = ChannelData(info, timestamps, samples, invalid_count, tuple(notes))
        while self.cache and self.cache_size + result.nbytes > self.cache_limit:
            _, evicted = self.cache.popitem(last=False)
            self.cache_size -= evicted.nbytes
        if result.nbytes <= self.cache_limit:
            self.cache[key] = result
            self.cache_size += result.nbytes
        return result

    def close(self) -> None:
        if self.mdf is not None:
            self.mdf.close()
            self.mdf = None
        self.channels.clear()
        self.cache.clear()
        self.cache_size = 0
