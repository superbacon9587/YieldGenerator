"""Compare 2 to 6 saved farm setups side by side (POST /api/compare).

Each setup is a full /api/simulate request. Every one runs through the same
engine, and the results are ranked by one summary_stats field:

    avg_profit            higher first (default)
    total_profit          higher first
    avg_relative_yield    higher first
    avg_water_applied_af  lower first

Setups whose ranking value is None (no price data) rank after every setup that
has a value. Equal values share a rank (1, 2, 2, 4). Results come back in rank
order; the input order breaks ties.
"""

from __future__ import annotations

from backend import simulate as sim
from backend.schemas import CompareRequest, CompareResponse, CompareResultOut

LOWER_IS_FIRST = {"avg_water_applied_af"}


def rank(values: list[float | None], lower_first: bool) -> list[int]:
    """Competition ranks for values, None last. Returns ranks in input order."""
    def key(i: int):
        v = values[i]
        return (v is None, (v if lower_first else -v) if v is not None else 0.0, i)

    order = sorted(range(len(values)), key=key)
    ranks = [0] * len(values)
    for pos, i in enumerate(order):
        prev = order[pos - 1] if pos else None
        same = prev is not None and values[prev] == values[i]
        ranks[i] = ranks[prev] if same else pos + 1
    return ranks


def compare(req: CompareRequest) -> CompareResponse:
    # Ranking only needs the summary, so skip the per-block system comparisons.
    responses = [sim.simulate(c.farm, include_comparisons=False) for c in req.configs]
    values = [getattr(r.summary_stats, req.ranked_by) for r in responses]
    ranks = rank(values, req.ranked_by in LOWER_IS_FIRST)
    results = [
        CompareResultOut(name=c.name.strip(), summary_stats=r.summary_stats,
                         budget=r.budget, rank=k)
        for c, r, k in zip(req.configs, responses, ranks)
    ]
    order = sorted(range(len(results)), key=lambda i: (results[i].rank, i))
    return CompareResponse(results=[results[i] for i in order], ranked_by=req.ranked_by)
