"""Demo scenarios. One scenario = one invoice plus the bank-ledger rows it should produce.

Used by (a) the offline mock PayPal client, (b) the sample bank ledger, and
(c) seed_sandbox.py which creates the same invoices in a real PayPal sandbox.
Dates are offsets from today so the demo never goes stale.
"""
from datetime import date, timedelta

from . import config


def net_of_fee(gross: float) -> float:
    return round(gross - (gross * config.FEE_PCT + config.FEE_FIXED), 2)


# status = what PayPal itself says. ledger = (day_offset, amount, description)
SCENARIOS = [
    # Earlier, fully settled invoices: give the income side a few months of history.
    dict(number="INV-0981", customer="Birch Studio", total=1800.00, status="PAID", issue=-78, due=-63, paid_on=-62,
         ledger=[(-61, 1800.00, "ACH CREDIT BIRCH STUDIO INV-0981")]),
    dict(number="INV-0982", customer="Acme Corp", total=2600.00, status="PAID", issue=-70, due=-55, paid_on=-56,
         ledger=[(-54, net_of_fee(2600.00), "PAYPAL TRANSFER INV-0982 ACME CORP")]),
    dict(number="INV-0983", customer="Harbor Foods", total=1450.00, status="PAID", issue=-48, due=-33, paid_on=-34,
         ledger=[(-32, 1450.00, "ACH CREDIT HARBOR FOODS INV-0983")]),
    dict(number="INV-0984", customer="Evergreen Farms", total=3100.00, status="PAID", issue=-42, due=-27, paid_on=-28,
         ledger=[(-26, 3100.00, "WIRE IN EVERGREEN FARMS INV-0984")]),
    dict(number="INV-1001", customer="Acme Corp", total=1200.00, status="PAID", issue=-40, due=-10, paid_on=-8,
         ledger=[(-7, net_of_fee(1200.00), "PAYPAL TRANSFER INV-1001 ACME CORP")]),
    dict(number="INV-1002", customer="Birch Studio", total=450.00, status="PAID", issue=-30, due=-5, paid_on=-6,
         ledger=[(-5, 450.00, "ACH CREDIT BIRCH STUDIO INV-1002")]),
    dict(number="INV-1003", customer="Cedar Logistics", total=3200.00, status="SENT", issue=-50, due=-20, ledger=[]),
    dict(number="INV-1004", customer="Delta Dental", total=780.00, status="PAID", issue=-25, due=-5, paid_on=-15,
         ledger=[(-14, 780.00, "ACH CREDIT DELTA DENTAL INV-1004"),
                 (-13, 780.00, "ACH CREDIT DELTA DENTAL INV-1004")]),
    dict(number="INV-1005", customer="Evergreen Farms", total=2000.00, status="PARTIALLY_PAID", issue=-35, due=-3,
         paid_amount=1000.00, paid_on=-9,
         ledger=[(-8, 1000.00, "WIRE IN EVERGREEN FARMS INV-1005")]),
    dict(number="INV-1006", customer="Fjord Design", total=615.50, status="SENT", issue=-5, due=10, ledger=[]),
    dict(number="INV-1007", customer="Granite Partners", total=1500.00, status="SENT", issue=-20, due=-2,
         ledger=[(-4, 1500.00, "WIRE IN GRANITE PARTNERS LLC")]),
    # --- Extra "fixable" items for demos: the bank already has the money, PayPal does not know yet. ---
    dict(number="INV-1011", customer="Kestrel Media", total=2250.00, status="SENT", issue=-18, due=-3,
         ledger=[(-2, 2250.00, "ACH CREDIT KESTREL MEDIA INV-1011")]),
    dict(number="INV-1012", customer="Lumen Health", total=960.00, status="PARTIALLY_PAID", issue=-28, due=-4,
         paid_amount=500.00, paid_on=-9,
         ledger=[(-9, 500.00, "ACH CREDIT LUMEN HEALTH INV-1012"),
                 (-2, 460.00, "ACH CREDIT LUMEN HEALTH INV-1012")]),   # second instalment not yet recorded in PayPal
    dict(number="INV-1013", customer="Maple Leaf Bakery", total=1800.00, status="SENT", issue=-15, due=10,
         ledger=[(-1, net_of_fee(1800.00), "PAYPAL TRANSFER INV-1013 MAPLE LEAF BAKERY")]),  # arrived net of fees
    dict(number="INV-1008", customer="Harbor Foods", total=920.00, status="PAID", issue=-22, due=-1, paid_on=-6,
         ledger=[(-5, 940.00, "ACH CREDIT HARBOR FOODS INV-1008")]),
    dict(number="INV-1009", customer="Indigo Labs", total=5400.00, status="PAID", issue=-30, due=-8, paid_on=-12,
         ledger=[]),
    dict(number="INV-1010", customer="Juniper Tech", total=275.00, status="CANCELLED", issue=-45, due=-15, ledger=[]),
]

# Ledger rows that match no invoice at all
EXTRA_LEDGER = [
    (-6, 333.33, "ZELLE FROM R MARTINEZ"),  # credit that matches no invoice
    # Debits: vendor spending. Ignored by reconciliation, used by the money in/out analytics.
    (-9, -2000.00, "ACH DEBIT OFFICE LEASE LLC"), (-39, -2000.00, "ACH DEBIT OFFICE LEASE LLC"),
    (-69, -2000.00, "ACH DEBIT OFFICE LEASE LLC"),
    (-12, -189.00, "CARD PURCHASE ADOBE SYSTEMS"), (-42, -189.00, "CARD PURCHASE ADOBE SYSTEMS"),
    (-72, -189.00, "CARD PURCHASE ADOBE SYSTEMS"),
    (-7, -642.18, "CARD PURCHASE STAPLES 0231"), (-36, -410.55, "CARD PURCHASE STAPLES 0231"),
    (-15, -310.40, "ACH DEBIT PACIFIC POWER"), (-45, -287.95, "ACH DEBIT PACIFIC POWER"),
    (-75, -301.10, "ACH DEBIT PACIFIC POWER"),
    (-20, -1250.00, "WIRE OUT ACME PACKAGING SUPPLY"), (-50, -980.00, "WIRE OUT ACME PACKAGING SUPPLY"),
    (-10, -540.00, "CARD PURCHASE GOOGLE ADS"), (-40, -615.00, "CARD PURCHASE GOOGLE ADS"),
    (-70, -495.00, "CARD PURCHASE GOOGLE ADS"),
    (-3, -79.00, "ACH DEBIT SLACK TECHNOLOGIES"), (-33, -79.00, "ACH DEBIT SLACK TECHNOLOGIES"),
]


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def mock_invoices() -> list[dict]:
    out = []
    for s in SCENARIOS:
        paid = s.get("paid_amount", s["total"] if s["status"] == "PAID" else 0.0)
        payments = []
        if paid:
            payments.append({"date": _d(s["paid_on"]), "amount": paid, "method": "BANK_TRANSFER"})
        out.append({
            "id": "INV2-" + s["number"][-4:] + "-MOCK",
            "number": s["number"],
            "status": s["status"],
            "customer": s["customer"],
            "email": s["customer"].split()[0].lower() + "@example.com",
            "currency": "USD",
            "total": s["total"],
            "paid_amount": paid,
            "due_amount": round(s["total"] - paid, 2) if s["status"] != "CANCELLED" else 0.0,
            "issue_date": _d(s["issue"]),
            "due_date": _d(s["due"]),
            "payments": payments,
        })
    return out


def sample_ledger() -> list[dict]:
    rows = []
    for s in SCENARIOS:
        for off, amt, desc in s["ledger"]:
            rows.append({"date": _d(off), "amount": amt, "description": desc})
    for off, amt, desc in EXTRA_LEDGER:
        rows.append({"date": _d(off), "amount": amt, "description": desc})
    rows.sort(key=lambda r: r["date"])
    for i, r in enumerate(rows):
        r["id"] = i
    return rows


def sample_ledger_csv() -> str:
    lines = ["date,amount,description"]
    for r in sample_ledger():
        lines.append(f'{r["date"]},{r["amount"]:.2f},"{r["description"]}"')
    return "\n".join(lines) + "\n"
