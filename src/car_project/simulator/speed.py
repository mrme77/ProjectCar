"""Realistic bounded speed variation for a simulated vehicle."""

from dataclasses import dataclass, field
from random import Random
from typing import Protocol


class GaussianSampler(Protocol):
    """The minimal random interface required by the normal speed profile."""

    def gauss(self, mu: float, sigma: float) -> float:
        """Return one normally distributed sample."""


@dataclass(slots=True)
class NormalSpeedProfile:
    """Vary a vehicle's speed around a target without unrealistic jumps.

    The target speed is the driver's intended pace. Each tick samples a normal
    distribution around that target, then clamps the result to legal simulation
    limits and an acceleration/deceleration limit.
    """

    target_speed_kmh: float
    standard_deviation_kmh: float = 5.0
    minimum_speed_kmh: float = 0.0
    maximum_speed_kmh: float = 250.0
    maximum_change_kmh_per_second: float = 10.0
    random_seed: int | None = None
    random_source: GaussianSampler | None = None
    current_speed_kmh: float = field(init=False)
    _random: GaussianSampler = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate the profile and initialize its deterministic starting speed."""
        if self.minimum_speed_kmh < 0.0:
            raise ValueError("minimum_speed_kmh must not be negative")
        if self.maximum_speed_kmh < self.minimum_speed_kmh:
            raise ValueError("maximum_speed_kmh must be at least minimum_speed_kmh")
        if not self.minimum_speed_kmh <= self.target_speed_kmh <= self.maximum_speed_kmh:
            raise ValueError("target_speed_kmh must be within the configured speed limits")
        if self.standard_deviation_kmh < 0.0:
            raise ValueError("standard_deviation_kmh must not be negative")
        if self.maximum_change_kmh_per_second <= 0.0:
            raise ValueError("maximum_change_kmh_per_second must be positive")
        self.current_speed_kmh = self.target_speed_kmh
        self._random = self.random_source or Random(self.random_seed)

    def set_target_speed(self, speed_kmh: float) -> None:
        """Set the driver's intended speed, preserving smooth movement changes."""
        if not self.minimum_speed_kmh <= speed_kmh <= self.maximum_speed_kmh:
            raise ValueError("speed_kmh must be within the configured speed limits")
        self.target_speed_kmh = speed_kmh
        if speed_kmh == 0.0:
            self.current_speed_kmh = 0.0

    def next_speed(
        self,
        elapsed_seconds: float,
        target_speed_kmh: float | None = None,
        variation_kmh: float | None = None,
        minimum_speed_kmh: float | None = None,
        maximum_speed_kmh: float | None = None,
    ) -> float:
        """Return the next actual speed after an optional traffic-control override."""
        if elapsed_seconds < 0.0:
            raise ValueError("elapsed_seconds must not be negative")
        effective_target = self.target_speed_kmh if target_speed_kmh is None else target_speed_kmh
        effective_variation = self.standard_deviation_kmh if variation_kmh is None else variation_kmh
        effective_minimum = self.minimum_speed_kmh if minimum_speed_kmh is None else minimum_speed_kmh
        effective_maximum = self.maximum_speed_kmh if maximum_speed_kmh is None else maximum_speed_kmh
        if effective_minimum < self.minimum_speed_kmh or effective_maximum > self.maximum_speed_kmh:
            raise ValueError("override speed bounds must be within the configured speed limits")
        if effective_minimum > effective_maximum:
            raise ValueError("override minimum speed must not exceed maximum speed")
        if not effective_minimum <= effective_target <= effective_maximum:
            raise ValueError("target_speed_kmh must be within the configured speed limits")
        if effective_variation < 0.0:
            raise ValueError("variation_kmh must not be negative")
        if effective_target == 0.0:
            self.current_speed_kmh = 0.0
            return self.current_speed_kmh
        if elapsed_seconds == 0.0:
            return self.current_speed_kmh

        sampled_speed = self._random.gauss(effective_target, effective_variation)
        desired_speed = min(effective_maximum, max(effective_minimum, sampled_speed))
        maximum_change = self.maximum_change_kmh_per_second * elapsed_seconds
        change = max(-maximum_change, min(maximum_change, desired_speed - self.current_speed_kmh))
        self.current_speed_kmh += change
        return self.current_speed_kmh
