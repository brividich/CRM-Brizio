"""Derivazione della fase iniziale della commessa (backfill una-tantum)."""
from __future__ import annotations


def derive_initial_phase(total: int, open_count: int, vrf_status: str) -> str:
    if total > 0 and open_count == 0:
        return "DONE"
    if open_count > 0:
        return "EXEC"
    if vrf_status == "UPLOADED":
        return "VRF"
    return "BOZZA"
