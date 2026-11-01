"""Claude tool-use agent. It reasons over deterministic findings and may only *propose* writes;
a human approves every PayPal change in the UI."""
import json

from . import config, store

SYSTEM = """You are LedgerLight, an accounts-receivable reconciliation analyst for a small business that
invoices through PayPal. Use the tools to fetch facts; never invent amounts, invoice numbers or dates, and
never do arithmetic yourself - quote the numbers the tools return. Be concise and specific: lead with what
matters most (largest/most severe exceptions), then recommended next steps. When a PayPal invoice status should
be updated to match money already in the bank, call propose_record_payment (a human will approve it; you cannot
execute it). When asked to write a customer message, draft it from get_invoice data in a polite, professional
tone and do not claim to have sent anything.

Wording rules: you are advising a small-business owner, so use plain language. Never state that a refund,
write-off or customer error is certain - say what to verify first (e.g. "check the bank statement, then refund
if the second payment is confirmed"). A deposit with no invoice is unexplained, not necessarily wrong.
You can draft a customer email with propose_email for overdue, partially paid, duplicate-paid or overpaid
invoices; a human reviews and approves every email before it is sent, so write it ready to send (greeting,
the exact amounts from the tools, one clear ask, polite sign-off) and never claim it was sent.
Format with short paragraphs and simple bullet lists; avoid tables and headings."""

TOOLS = [
    {"name": "get_reconciliation_report",
     "description": "Run reconciliation of PayPal invoices vs the bank ledger. Returns summary and ranked exceptions "
                    "(MISSING_DEPOSIT, OVERDUE, DUPLICATE_PAYMENT, OVERPAID, PARTIAL, STATUS_MISMATCH, UNMATCHED_DEPOSIT).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_invoice",
     "description": "Get one PayPal invoice (customer, email, totals, dates, payments) by invoice id.",
     "input_schema": {"type": "object", "properties": {"invoice_id": {"type": "string"}},
                      "required": ["invoice_id"]}},
    {"name": "propose_email",
     "description": "Queue a payment-related email to the invoice's customer for human approval. Does NOT send. "
                    "Use amounts exactly as returned by the tools.",
     "input_schema": {"type": "object",
                      "properties": {"invoice_id": {"type": "string"}, "subject": {"type": "string"},
                                     "body": {"type": "string"}, "reason": {"type": "string"}},
                      "required": ["invoice_id", "subject", "body"]}},
    {"name": "propose_record_payment",
     "description": "Queue a 'record payment' update on a PayPal invoice for human approval. Does NOT execute.",
     "input_schema": {"type": "object",
                      "properties": {"invoice_id": {"type": "string"}, "amount": {"type": "number"},
                                     "method": {"type": "string", "enum": ["BANK_TRANSFER", "CASH", "CHECK", "OTHER"]},
                                     "reason": {"type": "string"}},
                      "required": ["invoice_id", "amount", "reason"]}},
]


def run_tool(name: str, args: dict):
    try:
        if name == "get_reconciliation_report":
            return store.report()
        if name == "get_invoice":
            return store.client.get_invoice(args["invoice_id"])
        if name == "propose_record_payment":
            return store.propose(args["invoice_id"], float(args["amount"]),
                                 args.get("method", "BANK_TRANSFER"), args.get("reason", ""))
        if name == "propose_email":
            return store.propose_email(args["invoice_id"], args["subject"], args["body"], args.get("reason", ""))
        return {"error": f"unknown tool {name}"}
    except Exception as e:  # surfaced to the model so it can correct itself
        return {"error": str(e)}


def fallback_answer(message: str) -> str:
    """No API key: still useful. Plain summary of the deterministic report."""
    r = store.report()
    s = r["summary"]
    lines = [f"(Offline mode - set ANTHROPIC_API_KEY for the full agent.) Checked {s['invoices_checked']} invoices: "
             f"{s['reconciled']} reconciled, {s['exceptions']} exceptions, ${s['amount_at_risk']:,.2f} at risk."]
    lines += [f"- [{f['severity'].upper()}] {f['type']}: {f['detail']}" for f in r["findings"]]
    return "\n".join(lines)


def chat(message: str, history: list[dict] | None = None) -> dict:
    if not config.ANTHROPIC_API_KEY:
        return {"reply": fallback_answer(message), "tool_calls": []}
    try:
        return _chat_claude(message, history)
    except Exception as e:  # show the real cause (credit, model name, auth...) instead of a 500
        return {"reply": f"Claude API error ({type(e).__name__}): {e}\n\n" + fallback_answer(message),
                "tool_calls": []}


def _chat_claude(message: str, history: list[dict] | None = None) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    msgs = [{"role": h["role"], "content": h["content"]} for h in (history or [])
            if h.get("role") in ("user", "assistant") and h.get("content")]
    msgs.append({"role": "user", "content": message})
    calls = []
    for _ in range(8):
        resp = client.messages.create(model=config.CLAUDE_MODEL, max_tokens=1500, system=SYSTEM,
                                      tools=TOOLS, messages=msgs)
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            return {"reply": text, "tool_calls": calls}
        msgs.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                out = run_tool(b.name, b.input)
                calls.append({"name": b.name, "input": b.input})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out)})
        msgs.append({"role": "user", "content": results})
    return {"reply": "Stopped after too many tool steps.", "tool_calls": calls}
