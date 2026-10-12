"""Tests for bounded, reproducible normal-distribution speed variation."""

from car_project.simulator.speed import NormalSpeedProfile


class FixedGaussianSampler:
    """Return known normal-distribution samples for deterministic tests."""

    def __init__(self, samples: list[float]) -> None:
        """Store samples in the order the profile should consume them."""
        self._samples = samples

    def gauss(self, _mu: float, _sigma: float) -> float:
        """Return the next controlled sample without random behavior."""
        return self._samples.pop(0)


def test_speed_profile_limits_change_rate_and_keeps_values_within_bounds() -> None:
    """Extreme samples cannot make a car accelerate or brake unrealistically."""
    profile = NormalSpeedProfile(
        target_speed_kmh=80.0,
        standard_deviation_kmh=20.0,
        maximum_speed_kmh=120.0,
        maximum_change_kmh_per_second=5.0,
        random_source=FixedGaussianSampler([130.0, -20.0]),
    )

    accelerating_speed = profile.next_speed(1.0)
    braking_speed = profile.next_speed(1.0)

    assert accelerating_speed == 85.0
    assert braking_speed == 80.0


def test_speed_profile_seed_repeats_the_same_speed_pattern() -> None:
    """A seed makes a variable-speed test trip reproducible."""
    first_profile = NormalSpeedProfile(target_speed_kmh=80.0, random_seed=42)
    second_profile = NormalSpeedProfile(target_speed_kmh=80.0, random_seed=42)

    first_speeds = [first_profile.next_speed(1.0) for _ in range(4)]
    second_speeds = [second_profile.next_speed(1.0) for _ in range(4)]

    assert first_speeds == second_speeds
    assert all(0.0 <= speed <= 250.0 for speed in first_speeds)


def test_zero_target_speed_remains_stationary_despite_variation() -> None:
    """A stopped vehicle does not receive random positive speed samples."""
    profile = NormalSpeedProfile(target_speed_kmh=0.0, standard_deviation_kmh=5.0, random_seed=7)

    assert profile.next_speed(1.0) == 0.0
