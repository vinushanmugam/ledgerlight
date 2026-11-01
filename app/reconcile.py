"""Deterministic reconciliation: match bank-ledger credits to PayPal invoices and flag exceptions.

The LLM never does the arithmetic. It explains and acts on the findings produced here.
"""
import csv
import io
from datetime import date

from . import config

CLOSED = {"CANCELLED", "DRAFT", "REFUNDED"}
PAID = {"PAID", "MARKED_AS_PAID"}  # PayPal uses MARKED_AS_PAID when a payment is recorded out-of-band
UNPAID = {"SENT", "UNPAID", "SCHEDULED", "MARKED_AS_UNPAID"}
MATCH_THRESHOLD = 45


def net_of_fee(gross: float) -> float:
    return round(gross - (gross * config.FEE_PCT + config.FEE_FIXED), 2)


def parse_ledger_csv(text: str) -> list[dict]:
    """Expect columns: date, amount, description (extra columns ignored; header names case-insensitive)."""
    rows = []
    reader = csv.DictReader(io.StringIO(text.strip()))
    for i, raw in enumerate(reader):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        amt = r.get("amount", "").replace("$", "").replace(",", "")
        rows.append({"id": i, "date": r.get("date", ""), "amount": float(amt or 0),
                     "description": r.get("description") or r.get("memo") or r.get("reference") or ""})
    return rows


def _score(inv: dict, row: dict) -> int:
    text = row["description"].lower()
    s = 0
    if inv["number"] and inv["number"].lower() in text:
        s += 60
    amt, tot = row["amount"], inv["total"]
    if abs(amt - tot) <= 0.01 or abs(amt - net_of_fee(tot)) <= 0.02:
        s += 30
    elif s and amt < tot:  # reference matches and amount is smaller: plausible instalment
        s += 10
    elif s:                # reference matches but amount differs: still probably this invoice
        s += 0
    if any(t in text for t in inv["customer"].lower().split() if len(t) > 3):
        s += 15
    return s


def _credited(inv: dict, row: dict) -> float:
    """Gross value credited to the invoice by this deposit (deposits may arrive net of PayPal fees)."""
    return inv["total"] if abs(row["amount"] - net_of_fee(inv["total"])) <= 0.02 else row["amount"]


def _days_since(d: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat((d or "")[:10])).days
    except ValueError:
        return None


def reconcile(invoices: list[dict], ledger: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    active = [i for i in invoices if i["status"] not in CLOSED]
    credits = [r for r in ledger if r["amount"] > 0]

    matches: dict[str, list[tuple[dict, int]]] = {}
    unmatched = []
    for row in credits:
        best, best_s = None, 0
        for inv in active:
            s = _score(inv, row)
            if s > best_s:
                best, best_s = inv, s
        if best and best_s >= MATCH_THRESHOLD:
            matches.setdefault(best["id"], []).append((row, best_s))
        else:
            unmatched.append(row)

    findings, reconciled = [], []

    def add(type_, sev, inv, detail, amount, action=None, rows=()):
        findings.append({"type": type_, "severity": sev, "invoice_id": inv["id"], "invoice_number": inv["number"],
                         "customer": inv["customer"], "amount": round(amount, 2), "detail": detail,
                         "ledger_rows": [r["id"] for r in rows], "suggested_action": action,
                         "invoice": {k: inv.get(k) for k in ("status", "total", "paid_amount", "due_amount",
                                                              "issue_date", "due_date", "email")},
                         "ledger": [{"date": r["date"], "amount": r["amount"], "description": r["description"]}
                                    for r in rows]})

    for inv in active:
        rows = [r for r, _ in matches.get(inv["id"], [])]
        received = round(sum(_credited(inv, r) for r in rows), 2)
        diff = round(received - inv["total"], 2)
        due_days = _days_since(inv["due_date"], today)  # positive = overdue

        if not rows:
            if inv["status"] in PAID:
                age = _days_since((inv["payments"] or [{}])[-1].get("date"), today)
                if age is None or age >= config.DEPOSIT_GRACE_DAYS:
                    add("MISSING_DEPOSIT", "high", inv,
                        f"PayPal shows {inv['number']} paid (${inv['total']:,.2f}) but no matching bank deposit "
                        f"was found{'' if age is None else f' after {age} days'}.", inv["total"])
                else:
                    reconciled.append(inv["id"])
            elif inv["status"] in UNPAID and due_days is not None and due_days > 0:
                add("OVERDUE", "high" if due_days > 14 else "medium", inv,
                    f"{inv['number']} for ${inv['due_amount']:,.2f} is {due_days} days overdue with no payment seen "
                    f"in PayPal or the bank.", inv["due_amount"])
            continue

        if abs(diff) <= 0.02:
            if inv["status"] in UNPAID or (inv["status"] == "PARTIALLY_PAID" and inv["paid_amount"] + 0.02 < received):
                amt = round(received - inv["paid_amount"], 2)
                add("STATUS_MISMATCH", "medium", inv,
                    f"Bank shows ${received:,.2f} received for {inv['number']} but PayPal status is {inv['status']}.",
                    amt, {"tool": "record_payment", "invoice_id": inv["id"], "amount": amt,
                          "method": "BANK_TRANSFER"}, rows)
            else:
                reconciled.append(inv["id"])
        elif diff > 0:
            dup = len(rows) > 1 and any(abs(r["amount"] - rows[0]["amount"]) <= 0.01 for r in rows[1:]) \
                and abs(diff - _credited(inv, rows[-1])) <= 0.02
            if dup:
                add("DUPLICATE_PAYMENT", "high", inv,
                    f"{len(rows)} deposits of ~${rows[0]['amount']:,.2f} matched {inv['number']} "
                    f"(invoice total ${inv['total']:,.2f}). Likely double payment; ${diff:,.2f} may need refunding.",
                    diff, None, rows)
            else:
                add("OVERPAID", "medium", inv,
                    f"Received ${received:,.2f} against ${inv['total']:,.2f} for {inv['number']}: "
                    f"${diff:,.2f} over.", diff, None, rows)
        else:
            remaining = -diff
            add("PARTIAL", "medium", inv,
                f"Received ${received:,.2f} of ${inv['total']:,.2f} for {inv['number']}; "
                f"${remaining:,.2f} still outstanding.", remaining, None, rows)

    for r in unmatched:
        findings.append({"type": "UNMATCHED_DEPOSIT", "severity": "medium", "invoice_id": None,
                         "invoice_number": None, "customer": None, "amount": round(r["amount"], 2),
                         "detail": f"Deposit of ${r['amount']:,.2f} on {r['date']} ('{r['description']}') "
                                   f"matches no open invoice.", "ledger_rows": [r["id"]], "suggested_action": None,
                         "invoice": None,
                         "ledger": [{"date": r["date"], "amount": r["amount"], "description": r["description"]}]})

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f["severity"]], -f["amount"]))
    for n, f in enumerate(findings, 1):
        f["id"] = f"F{n}"

    return {
        "as_of": today.isoformat(),
        "ledger_loaded": bool(ledger),
        "summary": {
            "invoices_checked": len(active),
            "reconciled": len(reconciled),
            "exceptions": len(findings),
            "amount_at_risk": round(sum(f["amount"] for f in findings), 2),
            "ledger_credits": len(credits),
            "unmatched_deposits": len(unmatched),
        },
        "findings": findings,
    }
