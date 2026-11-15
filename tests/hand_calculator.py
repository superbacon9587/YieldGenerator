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
