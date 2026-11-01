# LedgerLight

An AI accounts-receivable reconciliation agent for small businesses that invoice with PayPal.

It compares your **PayPal invoices** (Invoicing API v2, sandbox) with your **bank ledger** (CSV), finds the exceptions a
bookkeeper would chase, and lets a Claude-powered agent explain them, draft customer follow-ups and *propose* fixes.
**Nothing is written to PayPal until a human clicks Approve.**

## What it catches

| Finding | Meaning |
|---|---|
| `MISSING_DEPOSIT` | PayPal says paid, but no matching bank deposit after a grace period |
| `OVERDUE` | Unpaid past due date, no payment anywhere |
| `DUPLICATE_PAYMENT` | Customer paid twice; refund likely needed |
| `OVERPAID` / `PARTIAL` | Received more or less than the invoice total |
| `STATUS_MISMATCH` | Bank has the money but PayPal invoice still shows unpaid (one-click fix after approval) |
| `UNMATCHED_DEPOSIT` | Bank credit that matches no open invoice |

Deposits that arrive **net of PayPal fees** are recognised (fee schedule configurable via `FEE_PCT` / `FEE_FIXED`).

## Design

- **Deterministic core** (`app/reconcile.py`): scoring-based matching and exception rules. All arithmetic lives here and is unit-tested.
- **Agent** (`app/agent.py`): Claude tool-use loop with three tools: `get_reconciliation_report`, `get_invoice`, `propose_record_payment`. It can read and propose, never execute.
- **Human approval queue** (`app/store.py`): proposed "record payment" actions wait for Approve/Reject in the UI; amounts are capped at the amount due.
- **PayPal** (`app/paypal_client.py`): OAuth2 client credentials, list/get invoices, record payment. A mock client with the same interface runs the whole app offline.

## Run it

```bash
pip install -r requirements.txt
python -m pytest -q                      # 9 tests
uvicorn app.main:app --reload            # http://localhost:8000  (mock PayPal + offline summaries)
```

Real sandbox + full agent:

```bash
export PAYPAL_CLIENT_ID=...  PAYPAL_CLIENT_SECRET=...   # developer.paypal.com > Apps & Credentials > Sandbox
export ANTHROPIC_API_KEY=...
python seed_sandbox.py --prefix T1- --ledger-out bank_ledger.csv   # creates demo invoices in your sandbox
uvicorn app.main:app
# then upload bank_ledger.csv in the UI
```

Bring your own data: upload any bank CSV with columns `date, amount, description`.

## Emailing customers about missing or partial payments

On any **overdue**, **partly paid**, **paid twice** or **overpaid** issue, click **Email customer**. LedgerLight drafts a polite
message using the exact amounts from the reconciliation, shows it in an editable window, and only sends when you click.
The recipient is always taken from the PayPal invoice, never typed in, and the assistant can queue emails too but only
you can approve them.

Without email settings the app runs in **demo mode**: "sending" saves the message to the in-app outbox and nothing leaves
your computer. To send for real, set these before starting the app:

```
set SMTP_HOST=smtp.gmail.com
set SMTP_PORT=587
set SMTP_USER=you@gmail.com
set SMTP_PASSWORD=your-app-password    (Gmail: create an App Password; never use your normal password)
set BUSINESS_NAME=Your Business Name
set EMAIL_OVERRIDE_TO=you@gmail.com    (recommended while demoing: every email goes to you, not the customer)
```

## Money in & out

The **Money in & out** tab reads the bank ledger: credits are income (grouped by client), debits are spending (grouped by
the payee name in the bank description). It shows totals, a month-by-month chart, top vendors and top clients. Income is
cash received, so it is after any PayPal fees.

## Configuration

`PAYPAL_ENV` (sandbox), `CLAUDE_MODEL` (default `claude-sonnet-4-5`), `FEE_PCT`, `FEE_FIXED`, `DEPOSIT_GRACE_DAYS`, `USE_MOCK`.

## Limits (honest list)

- Matching is heuristic (invoice number, amount incl. fee-net, customer name). Ambiguous cases surface as exceptions rather than being auto-resolved.
- Single currency per run; no refunds/chargebacks flow yet; ledger is in-memory per server process.
- Sandbox only. Do not point it at a live account without adding auth and persistence.

## AI disclosure

Built with AI coding assistance (Claude). Runtime uses Claude via the Anthropic API for explanation, drafting and action proposals.

License: MIT
