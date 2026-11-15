"""A person with a calculator, in code: redo a calculation record from its box alone.

Has its own tiny parser for + - * / and parentheses (no eval, and not the backend's
parser), so a bug in backend/calculations.py cannot hide itself.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

NUMBER = re.compile(r"\d+(?:\.\d+)?")


def half_up(x, digits):
    q = Decimal(repr(abs(x))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(q) * (-1 if x < 0 else 1) + 0.0


def calculate(expr):
    """Shunting-yard: numbers, + - * /, parentheses, unary minus."""
    out, ops = [], []
    prec = {"+": 1, "-": 1, "*": 2, "/": 2, "neg": 3}
    i, prev = 0, "op"
    while i < len(expr):
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        m = NUMBER.match(expr, i)
        if m:
            out.append(float(m.group()))
            i, prev = m.end(), "num"
            continue
        if c == "(":
            ops.append(c)
            prev = "op"
        elif c == ")":
            while ops[-1] != "(":
                out.append(ops.pop())
            ops.pop()
            prev = "num"
        elif c in "+-*/":
            op = "neg" if c == "-" and prev == "op" else c
            while ops and ops[-1] != "(" and op != "neg" and prec[ops[-1]] >= prec[op]:
                out.append(ops.pop())
            ops.append(op)
            prev = "op"
        else:
            raise AssertionError(f"Not basic arithmetic: {c!r} in {expr!r}")
        i += 1
    out += reversed(ops)
    stack = []
    for t in out:
        if isinstance(t, float):
            stack.append(t)
        elif t == "neg":
            stack.append(-stack.pop())
        else:
            b, a = stack.pop(), stack.pop()
            stack.append(a + b if t == "+" else a - b if t == "-" else a * b if t == "*" else a / b)
    assert len(stack) == 1, expr
    return stack[0]


def hand_check(rid, rec):
    """Every step uses only listed numbers, re-computes to its result, and ends on value."""
    assert rec["steps"], rid
    assert rec.get("rounding"), rid
    known = [abs(i["value"]) for i in rec["inputs"]
             if isinstance(i["value"], (int, float)) and not isinstance(i["value"], bool)]
    for step in rec["steps"]:
        for n in NUMBER.findall(step["expr"]):
            assert any(abs(float(n) - k) <= 1e-9 * max(1.0, k) for k in known), (rid, n, step, "not in the box")
        value = calculate(step["expr"])
        if step["round"] is not None:
            assert half_up(value, step["round"]) == step["result"], (rid, step)
        else:
            assert abs(value - step["result"]) <= 5e-7 * max(1.0, abs(value)), (rid, step)
        known.append(abs(step["result"]))
    assert rec["steps"][-1]["result"] == rec["value"], (rid, rec["steps"][-1], rec["value"])
    return len(rec["steps"])


# ---------------------------------------------------------------- cost, redone from the inputs alone

# Which published index scales each cost line (cost_components.csv index_name, as the
# record's index ratio steps name them). Lines with no index of their own (other inputs,
# irrigation system) use the dollar-weighted average ratio of the indexed lines.
COMPONENT_INDEX = {"Seed": "NASS seeds index", "Fertilizer": "NASS fertilizer index",
                   "Chemicals": "NASS chemicals index", "Labor": "NASS wage rate index",
                   "Machinery and fuel": "EIA diesel price", "Harvest and haul": "EIA diesel price"}
INDEX_NAME = re.compile(r"^(NASS .+ index|EIA diesel price), (\d{4})$")
AMOUNT_NAME = re.compile(r"^(Seed|Fertilizer|Chemicals|Labor|Machinery and fuel|Other inputs|Harvest and haul) "
                         r"per (acre|ton), (?:UC Davis .+ (\d{4}) study|USDA ERS U\.S\. total (\d{4}))$")


def redo_cost(rec):
    """Cost of one block in one year from the record's input values only (not its steps):
    inputs + harvest + water + irrigation system, with the rounding the record states.
    Returns {"inputs", "harvest", "water", "irrigation_system", "total"}."""
    by = {i["name"]: i["value"] for i in rec["inputs"]}
    acres = next(i["value"] for i in rec["inputs"] if i["unit"] == "acres")
    tons = next(i["value"] for i in rec["inputs"] if i["unit"] == "tons")

    index = {}
    for i in rec["inputs"]:
        m = INDEX_NAME.match(i["name"])
        if m:
            index.setdefault(m.group(1), {})[int(m.group(2))] = i["value"]

    def ratio(label, base_year):
        years = index[label]
        now = next((v for y, v in years.items() if y != base_year), years[base_year])
        return half_up(now / years[base_year], 6)

    lines = []  # (kind, amount, ratio or None for weighted/unscaled, ers)
    study_yield = next((v for n, v in by.items() if n.startswith("Yield in the UC Davis ")), None)
    for i in rec["inputs"]:
        m = AMOUNT_NAME.match(i["name"])
        if not m:
            continue
        kind, per, year = m.group(1), m.group(2), int(m.group(3) or m.group(4))
        ers = m.group(4) is not None
        r = None if ers or kind == "Other inputs" else ratio(COMPONENT_INDEX[kind], year)
        lines.append((kind, per, i["value"], r, ers))

    indexed = [(a * study_yield if per == "ton" else a, r) for _, per, a, r, _ in lines if r is not None]
    weight = sum(w for w, _ in indexed)
    weighted = half_up(sum(w * r for w, r in indexed) / weight, 6) if weight else 1.0

    def scale(r, ers):
        return 1.0 if ers else (weighted if r is None else r)

    per_acre = half_up(sum(a * scale(r, ers) for _, per, a, r, ers in lines if per == "acre"), 2)
    inputs = half_up(per_acre * acres, 2)
    harvest = half_up(sum(tons * a * scale(r, ers) for _, per, a, r, ers in lines if per == "ton"), 2)

    installed = [(n.split(": installed cost per acre")[0], v) for n, v in by.items() if ": installed cost per acre" in n]
    if installed:
        lives = {n.split(": system life")[0]: v for n, v in by.items() if ": system life" in n}
        per_year = half_up(sum(v / lives[line] for line, v in installed), 4)
    else:
        per_year = next(v for n, v in by.items() if n.startswith("Irrigation system, ") and " per acre per year" in n)
    system = half_up(per_year * weighted * acres, 2)

    water_af = by["Water applied (to 0.0001 acre-ft)"]
    share = by["Surface water share"]
    surface = groundwater = 0.0
    if share > 0:
        surface = half_up(half_up(water_af * share, 4) * by["Surface water price"], 2)
    if share < 1:
        gw_af = half_up(water_af * by["Groundwater share (1 - surface water share)"], 4)
        elec = next(v for n, v in by.items() if n.startswith("Electricity price, "))
        groundwater = half_up(gw_af * by["Well lift"] * by["Energy to lift 1 acre-ft by 1 ft"]
                              / by["Pump efficiency"] * elec, 2)
    water = half_up(surface + groundwater, 2)
    return {"inputs": inputs, "harvest": harvest, "water": water, "irrigation_system": system,
            "total": half_up(inputs + harvest + water + system, 0)}
