"""Minimal discrete-event simulation core.

Time is in seconds (float). Events are ordered on a heap by (time, seq).
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Callable


@dataclass(order=True)
class _Event:
    time: float
    seq: int
    cb: Callable[[], None] = field(compare=False)


class Engine:
    def __init__(self) -> None:
        self._heap: list[_Event] = []
        self._seq = 0
        self.now = 0.0

    def at(self, time: float, cb: Callable[[], None]) -> None:
        """Schedule callback `cb` to run at absolute time `time`."""
        if time < self.now:
            time = self.now
        heapq.heappush(self._heap, _Event(time, self._seq, cb))
        self._seq += 1

    def after(self, delay: float, cb: Callable[[], None]) -> None:
        self.at(self.now + max(0.0, delay), cb)

    def run(self, until: float | None = None) -> None:
        while self._heap:
            if until is not None and self._heap[0].time > until:
                break
            ev = heapq.heappop(self._heap)
            self.now = ev.time
            ev.cb()

    @property
    def empty(self) -> bool:
        return not self._heap
