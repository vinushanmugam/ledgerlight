"""In-memory app state: PayPal client, bank ledger, and the human-approval queue."""
import uuid
from datetime import datetime

from . import analytics, config, mailer, paypal_client, reconcile, sample_data

client = paypal_client.get_client()
ledger: list[dict] = []  # starts empty: the UI walks the user through adding bank data
prefix: str = ""  # set by load_sample_ledger() to the newest seeded invoice prefix, e.g. "T6-"
actions: dict[str, dict] = {}
outbox: list[dict] = []  # every email sent (or saved in demo mode)


def set_ledger_csv(text: str):
    global ledger
    ledger = reconcile.parse_ledger_csv(text)


def load_sample_ledger() -> int:
    """Load the demo bank ledger, re-pointed at whatever invoice numbers exist in PayPal.

    seed_sandbox.py prefixes invoice numbers (e.g. T5-INV-1001); this finds the newest open invoice
    ending in each demo number and rewrites the bank memo to match, so the demo works in any state.
    """
    global ledger, prefix
    rows = sample_data.sample_ledger()
    invs = client.list_invoices()
    found = set()
    for s in sample_data.SCENARIOS:
        base = s["number"]
        for i in invs:
            n = i["number"] or ""
            if n.endswith(base) and i["status"] not in reconcile.CLOSED:
                found.add(n[: len(n) - len(base)])
    # newest seed run wins (T10- after T9-); older runs are hidden so they don't mix in
    prefix = max(found, key=lambda p: (len(p), p)) if found else ""
    for s in sample_data.SCENARIOS:
        for r in rows:
            r["description"] = r["description"].replace(s["number"], prefix + s["number"])
    ledger = rows
    return len(ledger)


def visible_invoices() -> list[dict]:
    """Invoices in the current demo set. With no prefix selected, everything is shown."""
    return [i for i in client.list_invoices() if (i["number"] or "").startswith(prefix)]


def report() -> dict:
    return reconcile.reconcile(visible_invoices(), ledger)


def propose(invoice_id: str, amount: float, method: str = "BANK_TRANSFER", reason: str = "") -> dict:
    inv = next((i for i in client.list_invoices() if i["id"] == invoice_id), None)
    if not inv:
        raise ValueError(f"unknown invoice_id {invoice_id}")
    if amount <= 0 or amount > inv["due_amount"] + 0.005:
        raise ValueError(f"amount must be >0 and <= amount due (${inv['due_amount']:.2f})")
    if any(a["status"] == "pending" and a["tool"] == "record_payment" and a["invoice_id"] == invoice_id
           for a in actions.values()):
        raise ValueError(f"A fix for {inv['number']} is already waiting for your approval.")
    aid = uuid.uuid4().hex[:8]
    actions[aid] = {"id": aid, "tool": "record_payment", "invoice_id": invoice_id, "invoice_number": inv["number"],
                    "customer": inv["customer"], "amount": round(amount, 2), "method": method,
                    "reason": reason, "status": "pending"}
    return actions[aid]


def find_finding(invoice_id: str, kind: str) -> dict | None:
    return next((f for f in report()["findings"] if f["invoice_id"] == invoice_id and f["type"] == kind), None)


def email_draft(invoice_id: str, kind: str) -> dict:
    if kind not in mailer.KINDS:
        raise ValueError("emails are available for overdue, partial, duplicate and overpaid invoices")
    f = find_finding(invoice_id, kind)
    if not f:
        raise ValueError("that issue is no longer open")
    subject, body = mailer.build_draft(kind, f)
    to, redirected = mailer.recipient(f["invoice"]["email"])
    return {"invoice_id": invoice_id, "kind": kind, "customer": f["customer"], "invoice_number": f["invoice_number"],
            "to": to, "redirected": redirected, "customer_email": f["invoice"]["email"],
            "mode": mailer.mode(), "subject": subject, "body": body}


def send_email(invoice_id: str, subject: str, body: str, kind: str = "") -> dict:
    """The recipient is always derived from the invoice (or the demo override), never taken from the caller."""
    inv = next((i for i in client.list_invoices() if i["id"] == invoice_id), None)
    if not inv:
        raise ValueError(f"unknown invoice_id {invoice_id}")
    subject, body = (subject or "").strip(), (body or "").strip()
    if not subject or not body or len(subject) > 200 or len(body) > 5000:
        raise ValueError("subject and message are required (subject up to 200 characters, message up to 5,000)")
    to, redirected = mailer.recipient(inv["email"])
    status = mailer.send(to, subject, body)
    rec = {"id": uuid.uuid4().hex[:8], "status": status, "to": to, "customer_email": inv["email"],
           "redirected": redirected, "customer": inv["customer"], "invoice_number": inv["number"], "kind": kind,
           "subject": subject, "body": body, "at": datetime.now().isoformat(timespec="seconds")}
    outbox.append(rec)
    return rec


def propose_email(invoice_id: str, subject: str, body: str, reason: str = "") -> dict:
    inv = next((i for i in client.list_invoices() if i["id"] == invoice_id), None)
    if not inv:
        raise ValueError(f"unknown invoice_id {invoice_id}")
    to, _ = mailer.recipient(inv["email"])
    if "@" not in to:
        raise ValueError("this invoice has no customer email address")
    if not (subject or "").strip() or not (body or "").strip():
        raise ValueError("subject and body are required")
    aid = uuid.uuid4().hex[:8]
    actions[aid] = {"id": aid, "tool": "send_email", "invoice_id": invoice_id, "invoice_number": inv["number"],
                    "customer": inv["customer"], "to": to, "subject": subject.strip(), "body": body.strip(),
                    "reason": reason, "status": "pending"}
    return actions[aid]


def decide(action_id: str, approve: bool) -> dict:
    a = actions[action_id]
    if a["status"] != "pending":
        raise ValueError(f"action already {a['status']}")
    if not approve:
        a["status"] = "rejected"
        return a
    if a["tool"] == "send_email":
        rec = send_email(a["invoice_id"], a["subject"], a["body"])
        a["status"], a["result"] = "executed", {"email": rec["status"], "to": rec["to"]}
        return a
    # Re-check at approval time: the invoice may have changed since this fix was queued.
    inv = next((i for i in client.list_invoices() if i["id"] == a["invoice_id"]), None)
    if not inv or a["amount"] > inv["due_amount"] + 0.005:
        a["status"] = "rejected"
        raise ValueError(f"That fix is no longer needed: {a['invoice_number']} has only "
                         f"${(inv or {}).get('due_amount', 0):,.2f} left to pay. It was skipped.")
    res = client.record_payment(a["invoice_id"], a["amount"], a["method"])
    a["status"], a["result"] = "executed", res
    return a


def analytics_report() -> dict:
    return analytics.analyze(visible_invoices(), ledger)
