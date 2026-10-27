"""Shared synthetic dataset sizes and bounded portal households."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkProfile:
    patients: int
    history_rows: int
    pharmaceuticals: int


PROFILES = {
    "smoke": BenchmarkProfile(patients=100, history_rows=200, pharmaceuticals=20),
    "small": BenchmarkProfile(patients=1_000, history_rows=5_000, pharmaceuticals=100),
    "medium": BenchmarkProfile(patients=10_000, history_rows=50_000, pharmaceuticals=1_000),
    "large": BenchmarkProfile(patients=100_000, history_rows=500_000, pharmaceuticals=5_000),
}
MAX_PORTAL_HOUSEHOLDS = 64
MAX_FAMILY_MEMBERS = 8


def patient_identity(offset: int) -> str:
    return "370101199001011234" if offset == 0 else f"99000020000101{offset:06d}"


def portal_owner_offsets(profile: BenchmarkProfile) -> tuple[int, ...]:
    """Keep appointment target discovery independent of historical table size."""
    return tuple(range(0, min(profile.patients, MAX_PORTAL_HOUSEHOLDS * (MAX_FAMILY_MEMBERS + 1)), MAX_FAMILY_MEMBERS + 1))
