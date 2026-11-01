# Demo guide: recording LedgerLight

## Before every take (about 2 minutes)

Each take needs a fresh set of invoices, because approved fixes are permanent in the PayPal sandbox. Use a new prefix each time (`T8-`, `T9-`, ...).

```
uv run python seed_sandbox.py --prefix T8- --ledger-out bank_ledger.csv
```

Then restart the app (Ctrl+C, then `uv run uvicorn app.main:app`), press Ctrl+F5 in the browser, and click **Try the sample bank ledger**. The app automatically shows only your newest set.

For the recording set `EMAIL_OVERRIDE_TO` to your own address so no customer ever gets a real email, and set `DEPOSIT_GRACE_DAYS=0` so the missing-deposit item shows.

## What the sample data demonstrates

| Invoice | What happened | What to show |
|---|---|---|
| INV-1007 Granite Partners | Bank got $1,500, PayPal still says SENT | **Fix status in PayPal**, then Approve |
| INV-1011 Kestrel Media | Bank got $2,250, PayPal still says SENT | Second fix, same flow |
| INV-1012 Lumen Health | Paid in two instalments, PayPal only knows the first | Fix records only the missing **$460.00** |
| INV-1013 Maple Leaf Bakery | $1,800 invoice, bank got less because of PayPal fees | Shows fee-aware matching; fix records the full $1,800 |
| INV-1003 Cedar Logistics | $3,200 overdue | **Email customer** (saved to outbox in demo mode) |
| INV-1005 Evergreen Farms | Half paid | **Email customer** about the balance |
| INV-1004 Delta Dental | Paid twice | **Ask assistant** to explain; email about a refund or credit |
| INV-1009 Indigo Labs | PayPal says paid, no bank deposit | The "$5,400 missing" headline |

## Suggested click order (about 2.5 minutes)

1. Welcome screen, click **Try the sample bank ledger**. Point at the red "Money to chase or check" tile.
2. **Issues** tab: read the top two items. Open **Show details** on INV-1012 to show invoice vs bank side by side.
3. Click **Fix status in PayPal** on INV-1007, INV-1011 and INV-1012. Each button turns into "Waiting for your approval". Say that nothing has changed in PayPal yet.
4. In the approvals panel, **Approve & update PayPal** on all three. Watch "Matched & settled" climb and the red total drop.
5. **Email customer** on Cedar Logistics. Show the editable draft, then Save/Send. The message appears under "Messages to customers".
6. **Money in & out** tab: income vs vendor spending, top vendor, top client.
7. Ask the assistant: "What should I deal with first?" (needs `ANTHROPIC_API_KEY`).
8. Show the sandbox dashboard with the invoice now marked paid (log in at sandbox.paypal.com with the business account).

Leave INV-1013 for a second take or a bonus shot, so you have a fix left over if something goes wrong.
