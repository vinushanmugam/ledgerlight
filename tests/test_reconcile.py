from app import reconcile, sample_data, store, agent
from app.paypal_client import MockPayPalClient, normalize


def _report():
    return reconcile.reconcile(MockPayPalClient().list_invoices(), sample_data.sample_ledger())


def _types(rep):
    return {(f["invoice_number"], f["type"]) for f in rep["findings"]}


def test_expected_findings():
    t = _types(_report())
    assert ("INV-1003", "OVERDUE") in t
    assert ("INV-1004", "DUPLICATE_PAYMENT") in t
    assert ("INV-1005", "PARTIAL") in t
    assert ("INV-1007", "STATUS_MISMATCH") in t
    assert ("INV-1008", "OVERPAID") in t
    assert ("INV-1009", "MISSING_DEPOSIT") in t
    assert (None, "UNMATCHED_DEPOSIT") in t


def test_clean_invoices_are_not_flagged():
    flagged = {f["invoice_number"] for f in _report()["findings"]}
    assert not flagged & {"INV-1001", "INV-1002", "INV-1006", "INV-1010"}  # net-of-fee, exact, not-yet-due, cancelled


def test_amounts():
    by = {(f["invoice_number"], f["type"]): f for f in _report()["findings"]}
    assert by[("INV-1004", "DUPLICATE_PAYMENT")]["amount"] == 780.00
    assert by[("INV-1008", "OVERPAID")]["amount"] == 20.00
    assert by[("INV-1005", "PARTIAL")]["amount"] == 1000.00
    assert by[("INV-1007", "STATUS_MISMATCH")]["suggested_action"]["amount"] == 1500.00


def test_debits_ignored():
    rep = _report()
    assert rep["summary"]["ledger_credits"] == len([r for r in sample_data.sample_ledger() if r["amount"] > 0])


def test_csv_roundtrip():
    rows = reconcile.parse_ledger_csv(sample_data.sample_ledger_csv())
    assert len(rows) == len(sample_data.sample_ledger())


def test_approval_flow_updates_invoice():
    store.client = MockPayPalClient()
    store.actions.clear()
    store.ledger = sample_data.sample_ledger()
    assert ("INV-1007", "STATUS_MISMATCH") in _types(store.report())
    inv = next(i for i in store.client.list_invoices() if i["number"] == "INV-1007")
    a = store.propose(inv["id"], 1500.00, reason="test")
    assert a["status"] == "pending" and store.client.get_invoice(inv["id"])["status"] == "SENT"
    store.decide(a["id"], True)
    assert store.client.get_invoice(inv["id"])["status"] == "PAID"
    assert ("INV-1007", "STATUS_MISMATCH") not in _types(store.report())


def test_cannot_overpay_via_action():
    store.client = MockPayPalClient()
    inv = next(i for i in store.client.list_invoices() if i["number"] == "INV-1006")
    try:
        store.propose(inv["id"], inv["total"] + 1)
        assert False
    except ValueError:
        pass


def test_normalize_paypal_shape():
    n = normalize({"id": "INV2-X", "status": "SENT",
                   "detail": {"invoice_number": "A1", "invoice_date": "2026-10-01",
                              "payment_term": {"due_date": "2026-10-15"}, "currency_code": "USD"},
                   "primary_recipients": [{"billing_info": {"name": {"given_name": "Ann", "surname": "Lee"},
                                                            "email_address": "a@x.com"}}],
                   "amount": {"currency_code": "USD", "value": "74.21"}})
    assert n["number"] == "A1" and n["customer"] == "Ann Lee" and n["total"] == 74.21 and n["due_amount"] == 74.21


def test_agent_offline_fallback():
    store.client = MockPayPalClient()
    out = agent.chat("summary")
    assert "exceptions" in out["reply"]


def test_marked_as_paid_status_is_treated_as_paid():
    invs = MockPayPalClient().list_invoices()
    for i in invs:
        if i["status"] == "PAID":
            i["status"] = "MARKED_AS_PAID"
    rep = reconcile.reconcile(invs, sample_data.sample_ledger())
    t = _types(rep)
    assert ("INV-1009", "MISSING_DEPOSIT") in t
    assert ("INV-1004", "DUPLICATE_PAYMENT") in t
    assert not {f["invoice_number"] for f in rep["findings"]} & {"INV-1001", "INV-1002"}


def test_sample_ledger_follows_live_invoice_prefix():
    store.client = MockPayPalClient()
    for i in store.client._inv.values():
        i["number"] = "T9-" + i["number"]
    store.ledger = []
    assert store.report()["ledger_loaded"] is False
    store.load_sample_ledger()
    rep = store.report()
    assert rep["ledger_loaded"] is True
    t = _types(rep)
    assert ("T9-INV-1004", "DUPLICATE_PAYMENT") in t and ("T9-INV-1009", "MISSING_DEPOSIT") in t


def test_findings_carry_details_for_the_ui():
    rep = _report()
    dup = next(f for f in rep["findings"] if f["type"] == "DUPLICATE_PAYMENT")
    assert dup["invoice"]["total"] == 780.0 and len(dup["ledger"]) == 2
    un = next(f for f in rep["findings"] if f["type"] == "UNMATCHED_DEPOSIT")
    assert un["invoice"] is None and len(un["ledger"]) == 1


def test_sample_ledger_uses_only_newest_seed_run():
    store.client = MockPayPalClient()
    base = list(store.client._inv.values())
    store.client._inv = {}
    for pre in ("T5-", "T6-"):
        for i in base:
            c = dict(i, id=pre + i["id"], number=pre + i["number"], payments=list(i["payments"]))
            store.client._inv[c["id"]] = c
    store.load_sample_ledger()
    rep = store.report()
    nums = {f["invoice_number"] for f in rep["findings"] if f["invoice_number"]}
    assert nums and all(n.startswith("T6-") for n in nums)
    assert all(i["number"].startswith("T6-") for i in store.visible_invoices())
    store.prefix = ""  # don't leak into other tests



# ---------- email ----------
from app import analytics, config, mailer  # noqa: E402


def _fresh():
    store.client = MockPayPalClient()
    store.ledger = sample_data.sample_ledger()
    store.prefix = ""
    store.actions.clear()
    store.outbox.clear()
    config.EMAIL_OVERRIDE_TO = ""
    config.SMTP_HOST = config.SMTP_USER = config.SMTP_PASSWORD = ""


def _inv(number):
    return next(i for i in store.client.list_invoices() if i["number"] == number)


def test_email_draft_uses_engine_amounts():
    _fresh()
    d = store.email_draft(_inv("INV-1003")["id"], "OVERDUE")
    assert d["to"] == "cedar@example.com" and "$3,200.00" in d["body"] and "INV-1003" in d["subject"]
    d = store.email_draft(_inv("INV-1005")["id"], "PARTIAL")
    assert "$1,000.00 outstanding" in d["body"]
    d = store.email_draft(_inv("INV-1004")["id"], "DUPLICATE_PAYMENT")
    assert "$780.00" in d["subject"] and "refund or a credit" in d["body"]


def test_email_demo_mode_saves_to_outbox_and_not_sent():
    _fresh()
    rec = store.send_email(_inv("INV-1003")["id"], "Hi", "Please pay")
    assert rec["status"] == "saved" and store.outbox[-1]["to"] == "cedar@example.com"


def test_email_override_redirects_every_message():
    _fresh()
    config.EMAIL_OVERRIDE_TO = "me@example.org"
    d = store.email_draft(_inv("INV-1003")["id"], "OVERDUE")
    assert d["to"] == "me@example.org" and d["redirected"] and d["customer_email"] == "cedar@example.com"
    assert store.send_email(_inv("INV-1003")["id"], "s", "b")["to"] == "me@example.org"
    config.EMAIL_OVERRIDE_TO = ""


def test_email_rejects_unsupported_kinds_and_empty_messages():
    _fresh()
    for fn in (lambda: store.email_draft(_inv("INV-1007")["id"], "STATUS_MISMATCH"),
               lambda: store.send_email(_inv("INV-1003")["id"], "", "x"),
               lambda: store.send_email("nope", "s", "b")):
        try:
            fn()
            assert False
        except ValueError:
            pass


def test_agent_proposed_email_needs_approval():
    _fresh()
    a = store.propose_email(_inv("INV-1003")["id"], "Overdue", "Please pay $3,200.00", "overdue 20 days")
    assert a["status"] == "pending" and store.outbox == []
    store.decide(a["id"], True)
    assert len(store.outbox) == 1 and store.actions[a["id"]]["status"] == "executed"
    b = store.propose_email(_inv("INV-1003")["id"], "again", "again")
    store.decide(b["id"], False)
    assert len(store.outbox) == 1


# ---------- analytics ----------
def test_payee_cleanup():
    assert analytics.payee("CARD PURCHASE STAPLES 0231") == "Staples"
    assert analytics.payee("ACH DEBIT OFFICE LEASE LLC") == "Office Lease LLC"
    assert analytics.payee("WIRE OUT ACME PACKAGING SUPPLY") == "Acme Packaging Supply"
    assert analytics.payee("ZELLE FROM R MARTINEZ") == "R Martinez"


def test_analytics_splits_income_and_spending():
    _fresh()
    a = store.analytics_report()
    led = sample_data.sample_ledger()
    assert a["income"] == round(sum(r["amount"] for r in led if r["amount"] > 0), 2)
    assert a["spending"] == round(-sum(r["amount"] for r in led if r["amount"] < 0), 2)
    assert a["net"] == round(a["income"] - a["spending"], 2)
    vend = {v["name"]: v["total"] for v in a["vendors"]}
    assert vend["Office Lease LLC"] == 6000.0 and vend["Adobe Systems"] == 567.0
    clients = {c["name"] for c in a["clients"]}
    assert "Harbor Foods" in clients                       # income is grouped under the matched PayPal customer
    assert round(sum(c["total"] for c in a["clients"]), 2) == a["income"]  # small clients roll into "N others"
    assert abs(sum(v["share"] for v in a["vendors"]) - 100) < 0.5
    assert len(a["monthly"]) >= 3
    store.ledger = []
    assert store.analytics_report() == {"ledger_loaded": False}


def test_demo_fixable_items_and_approving_them_all():
    _fresh()
    rep = store.report()
    fixable = {f["invoice_number"]: f for f in rep["findings"] if f["suggested_action"]}
    assert set(fixable) == {"INV-1007", "INV-1011", "INV-1012", "INV-1013"}
    assert fixable["INV-1011"]["suggested_action"]["amount"] == 2250.00
    assert fixable["INV-1012"]["suggested_action"]["amount"] == 460.00   # only the unrecorded instalment
    assert fixable["INV-1013"]["suggested_action"]["amount"] == 1800.00  # deposit was net of fees, invoice is paid in full
    for f in fixable.values():
        a = f["suggested_action"]
        act = store.propose(a["invoice_id"], a["amount"], a["method"], "demo")
        store.decide(act["id"], True)
    after = store.report()
    assert not [f for f in after["findings"] if f["type"] == "STATUS_MISMATCH"]
    assert after["summary"]["exceptions"] == rep["summary"]["exceptions"] - 4


def test_duplicate_and_stale_fixes_are_blocked():
    _fresh()
    inv = _inv("INV-1007")
    first = store.propose(inv["id"], 1500.00, reason="a")
    try:
        store.propose(inv["id"], 1500.00, reason="again")
        assert False, "second pending fix for the same invoice must be refused"
    except ValueError as e:
        assert "already waiting" in str(e)
    # a fix queued earlier, then the invoice gets settled another way -> approving must not double-pay
    store.client.record_payment(inv["id"], 1500.00)
    try:
        store.decide(first["id"], True)
        assert False
    except ValueError as e:
        assert "no longer needed" in str(e)
    assert store.actions[first["id"]]["status"] == "rejected"
    assert _inv("INV-1007")["paid_amount"] == 1500.00

