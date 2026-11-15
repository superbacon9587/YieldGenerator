"""Half-up decimal rounding shared by the engine, the calculation records, and the UI.

rnd(2.675, 2) is 2.68 and rnd(-0.5) is -1: the shortest decimal form of the float
(repr) is rounded half away from zero, the way a person rounds on paper.
frontend/src/features/provenance/chartData.js implements the same rule, so a value
rounded in Python and in the browser is the same number.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def rnd(x: float | None, digits: int = 0) -> float | None:
    if x is None:
        return None
    q = Decimal(repr(abs(float(x)))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(q) * (-1.0 if x < 0 else 1.0) + 0.0


def exact_sum(values) -> float:
    """Sum of decimal numbers as a person adds them: the float sum snapped back to 6
    decimals, so 0.996 + 0.999 + 1.001 + 1.001 + 0.986 + 1.002 is 5.985, not 5.98499999."""
    return rnd(sum(values), 6)


def mean(values) -> float | None:
    """exact_sum / count, or None for no values."""
    values = [v for v in values if v is not None]
    return exact_sum(values) / len(values) if values else None
