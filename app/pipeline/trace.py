"""Chronomètre des étapes, pour la ligne « comment le verdict a été produit »."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from .models import StageTiming, Trace


class Stopwatch:
    """Mesure chaque étape et les range dans la trace."""

    def __init__(self, trace: Trace) -> None:
        self.trace = trace
        self.started = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.trace.timings.append(StageTiming(stage=name, ms=int((time.perf_counter() - start) * 1000)))

    def close(self) -> None:
        self.trace.total_ms = int((time.perf_counter() - self.started) * 1000)
