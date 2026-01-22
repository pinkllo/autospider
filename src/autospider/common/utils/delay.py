"""Delay helpers shared across crawler components."""

from __future__ import annotations

import random


def get_random_delay(base: float, random_range: float) -> float:
    """Return a randomized delay in seconds."""
    return base + random.uniform(0, random_range)
