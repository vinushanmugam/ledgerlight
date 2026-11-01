"""Create the demo invoices in YOUR PayPal sandbox so the app runs on real sandbox data.

    export PAYPAL_CLIENT_ID=... PAYPAL_CLIENT_SECRET=...
    python seed_sandbox.py [--prefix T1-]

Not yet run against a live sandbox by the author: PayPal may reject past due dates or duplicate
invoice numbers. Failures are printed per invoice; re-run with a new --prefix to avoid clashes.
Afterwards, export the ledger with:  curl localhost:8000/api/sample-ledger.csv  (invoice numbers carry the prefix,
so regenerate it with --ledger-out to match).
"""
import argparse
import os
from datetime import date, timedelta

from app import sample_data
from app.paypal_client import PayPalClient


def build(s: dict, prefix: str) -> dict:
    d = lambda off: (date.today() + timedelta(days=off)).isoformat()
    return {
        "detail": {"invoice_number": prefix + s["number"], "invoice_date": d(s["issue"]), "currency_code": "USD",
                   "payment_term": {"term_type": "DUE_ON_DATE_SPECIFIED", "due_date": d(s["due"])}},
        # Seller defaults to your app's sandbox business account. To force one, set PAYPAL_MERCHANT_EMAIL
        # to the email of a Business account under Testing Tools > Sandbox Accounts.
        **({"invoicer": {"email_address": os.environ["PAYPAL_MERCHANT_EMAIL"]}}
           if os.getenv("PAYPAL_MERCHANT_EMAIL") else {}),
        "primary_recipients": [{"billing_info": {"business_name": s["customer"],
                                                 "email_address": s["customer"].split()[0].lower() + "@example.com"}}],
        "items": [{"name": "Services", "quantity": "1", "unit_amount": {"currency_code": "USD",
                                                                          "value": f'{s["total"]:.2f}'}}],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="")
    ap.add_argument("--ledger-out", help="write a matching bank-ledger CSV to this path")
    a = ap.parse_args()
    pp = PayPalClient()
    for s in sample_data.SCENARIOS:
        if s["status"] == "CANCELLED":
            continue
        try:
            inv = pp.create_invoice(build(s, a.prefix))
            inv_id = inv["href"].rsplit("/", 1)[-1] if "href" in inv else inv.get("id")
            pp.send_invoice(inv_id)
            paid = s.get("paid_amount", s["total"] if s["status"] == "PAID" else 0)
            if paid:
                pp.record_payment(inv_id, paid, "BANK_TRANSFER")
            print("ok  ", a.prefix + s["number"], inv_id)
        except Exception as e:
            print("FAIL", a.prefix + s["number"], e)
    if a.ledger_out:
        text = sample_data.sample_ledger_csv()
        for s in sample_data.SCENARIOS:
            text = text.replace(s["number"], a.prefix + s["number"])
        open(a.ledger_out, "w").write(text)
        print("wrote", a.ledger_out)
