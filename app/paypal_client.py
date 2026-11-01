"""Thin PayPal Invoicing v2 client (sandbox by default) plus an offline mock with the same interface."""
import time
import uuid

import httpx

from . import config, sample_data

BASE = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def normalize(inv: dict) -> dict:
    """Flatten a PayPal v2 invoice object into the small shape the rest of the app uses."""
    detail = inv.get("detail", {}) or {}
    amount = inv.get("amount", {}) or {}
    rec = ((inv.get("primary_recipients") or [{}])[0]).get("billing_info", {}) or {}
    name = rec.get("name", {}) or {}
    customer = (rec.get("business_name") or name.get("full_name")
                or " ".join(x for x in [name.get("given_name"), name.get("surname")] if x))
    total = _f(amount.get("value"))
    payments = [
        {"date": p.get("payment_date"), "amount": _f((p.get("amount") or {}).get("value")), "method": p.get("method")}
        for p in ((inv.get("payments") or {}).get("transactions") or [])
    ]
    due = inv.get("due_amount")
    due_amount = _f(due.get("value")) if due else None
    paid = round(total - due_amount, 2) if due_amount is not None else round(sum(p["amount"] for p in payments), 2)
    term = detail.get("payment_term") or {}
    return {
        "id": inv.get("id"),
        "number": detail.get("invoice_number"),
        "status": inv.get("status"),
        "customer": customer or "",
        "email": rec.get("email_address", ""),
        "currency": detail.get("currency_code") or amount.get("currency_code") or "USD",
        "total": total,
        "paid_amount": paid,
        "due_amount": due_amount if due_amount is not None else round(total - paid, 2),
        "issue_date": detail.get("invoice_date"),
        "due_date": term.get("due_date"),
        "payments": payments,
    }


class PayPalClient:
    mode = "sandbox"

    def __init__(self, client_id=None, secret=None, env=None):
        self.client_id = client_id or config.PAYPAL_CLIENT_ID
        self.secret = secret or config.PAYPAL_CLIENT_SECRET
        self.base = BASE[env or config.PAYPAL_ENV]
        self.mode = env or config.PAYPAL_ENV
        self._tok, self._exp = None, 0.0
        self.http = httpx.Client(timeout=30)

    def _token(self) -> str:
        if self._tok and time.time() < self._exp - 60:
            return self._tok
        r = self.http.post(f"{self.base}/v1/oauth2/token", auth=(self.client_id, self.secret),
                           data={"grant_type": "client_credentials"})
        r.raise_for_status()
        j = r.json()
        self._tok, self._exp = j["access_token"], time.time() + j.get("expires_in", 300)
        return self._tok

    def _req(self, method, path, **kw):
        h = {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}
        r = self.http.request(method, f"{self.base}{path}", headers=h, **kw)
        if r.status_code >= 400:
            # PayPal puts the useful explanation in the response body
            raise RuntimeError(f"PayPal {r.status_code} on {method} {path}: {r.text[:600]}")
        return r.json() if r.content else {}

    def list_invoices(self) -> list[dict]:
        out, page = [], 1
        while True:
            j = self._req("GET", "/v2/invoicing/invoices",
                          params={"page": page, "page_size": 100, "total_required": "true"})
            out += [normalize(i) for i in j.get("items", [])]
            if page >= j.get("total_pages", 1):
                return out
            page += 1

    def get_invoice(self, invoice_id: str) -> dict:
        return normalize(self._req("GET", f"/v2/invoicing/invoices/{invoice_id}"))

    def record_payment(self, invoice_id: str, amount: float, method: str = "BANK_TRANSFER", currency="USD") -> dict:
        body = {"method": method, "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
                "note": "Recorded by LedgerLight after bank-ledger match (human approved)"}
        return self._req("POST", f"/v2/invoicing/invoices/{invoice_id}/payments", json=body)

    # --- used only by seed_sandbox.py ---
    def create_invoice(self, body: dict) -> dict:
        return self._req("POST", "/v2/invoicing/invoices", json=body)

    def send_invoice(self, invoice_id: str) -> dict:
        # Default send settings (recipient notified). Sandbox does not deliver real email.
        return self._req("POST", f"/v2/invoicing/invoices/{invoice_id}/send", json={})


class MockPayPalClient:
    """Offline stand-in so the app (and tests) run without credentials."""
    mode = "mock"

    def __init__(self):
        self._inv = {i["id"]: i for i in sample_data.mock_invoices()}

    def list_invoices(self):
        return [dict(i) for i in self._inv.values()]

    def get_invoice(self, invoice_id):
        return dict(self._inv[invoice_id])

    def record_payment(self, invoice_id, amount, method="BANK_TRANSFER", currency="USD"):
        inv = self._inv[invoice_id]
        inv["payments"].append({"date": sample_data._d(0), "amount": amount, "method": method})
        inv["paid_amount"] = round(inv["paid_amount"] + amount, 2)
        inv["due_amount"] = round(inv["total"] - inv["paid_amount"], 2)
        inv["status"] = "PAID" if inv["due_amount"] <= 0.005 else "PARTIALLY_PAID"
        return {"payment_id": "MOCK-" + uuid.uuid4().hex[:8]}


def get_client():
    return MockPayPalClient() if config.USE_MOCK else PayPalClient()
