"""Money in vs money out, from the bank ledger.

Credits are income, grouped by client (matched to a PayPal invoice when possible, else by payee text).
Debits are spending, grouped by payee/vendor parsed from the bank description.
"""
import re
from collections import defaultdict
from datetime import datetime

from . import reconcile

_PREFIX = re.compile(
    r"^(ACH|WIRE|CARD|POS|CHECKCARD|DEBIT|CREDIT|PAYMENT|PURCHASE|TRANSFER|ONLINE|OUT|IN|FROM|TO|ZELLE)\b[\s:*-]*",
    re.I)
_UPPER = {"LLC", "INC", "LTD", "CO", "LLP", "USA"}


def payee(desc: str) -> str:
    """'CARD PURCHASE STAPLES 0231' -> 'Staples'. Strips bank boilerplate and reference numbers."""
    s = (desc or "").upper().strip()
    for _ in range(5):
        t = _PREFIX.sub("", s, count=1)
        if t == s:
            break
        s = t
    words = [w for w in re.split(r"[\s*#]+", s) if w and not any(c.isdigit() for c in w)]
    if not words:
        return (desc or "Unknown").title()
    return " ".join(w if w in _UPPER else w.capitalize() for w in words[:3])


def _month(d: str) -> str:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y"):
        try:
            return datetime.strptime((d or "").strip(), fmt).strftime("%Y-%m")
        except ValueError:
            pass
    return "unknown"


def _top(by: dict, count: dict, limit: int = 7) -> list[dict]:
    total = sum(by.values()) or 1.0
    items = sorted(by.items(), key=lambda kv: -kv[1])
    rows = [{"name": k, "total": round(v, 2), "count": count[k], "share": round(v / total * 100, 1)}
            for k, v in items[:limit]]
    rest = items[limit:]
    if rest:
        v = sum(x for _, x in rest)
        rows.append({"name": f"{len(rest)} others", "total": round(v, 2), "count": sum(count[k] for k, _ in rest),
                     "share": round(v / total * 100, 1)})
    return rows


def analyze(invoices: list[dict], ledger: list[dict]) -> dict:
    if not ledger:
        return {"ledger_loaded": False}
    active = [i for i in invoices if i["status"] not in reconcile.CLOSED]
    inc, spend = defaultdict(float), defaultdict(float)
    inc_n, spend_n = defaultdict(int), defaultdict(int)
    monthly = defaultdict(lambda: {"income": 0.0, "spending": 0.0})
    for r in ledger:
        amt, m = r["amount"], _month(r["date"])
        if amt > 0:
            score, inv = max(((reconcile._score(i, r), i) for i in active), key=lambda x: x[0], default=(0, None))
            name = inv["customer"] if inv and score >= reconcile.MATCH_THRESHOLD else payee(r["description"])
            inc[name] += amt
            inc_n[name] += 1
            monthly[m]["income"] += amt
        elif amt < 0:
            name = payee(r["description"])
            spend[name] += -amt
            spend_n[name] += 1
            monthly[m]["spending"] += -amt
    income, spending = round(sum(inc.values()), 2), round(sum(spend.values()), 2)
    dates = sorted(r["date"] for r in ledger if r["date"])
    return {
        "ledger_loaded": True,
        "income": income, "spending": spending, "net": round(income - spending, 2),
        "monthly": [{"month": k, "income": round(v["income"], 2), "spending": round(v["spending"], 2)}
                    for k, v in sorted(monthly.items()) if k != "unknown"],
        "vendors": _top(spend, spend_n), "clients": _top(inc, inc_n),
        "rows": len(ledger), "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
    }
