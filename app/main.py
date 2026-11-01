from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import agent, config, mailer, sample_data, store

app = FastAPI(title="LedgerLight")
STATIC = Path(__file__).parent / "static"


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


class EmailDraftIn(BaseModel):
    invoice_id: str
    kind: str


class EmailSendIn(BaseModel):
    invoice_id: str
    subject: str
    body: str
    kind: str = ""


class ActionIn(BaseModel):
    invoice_id: str
    amount: float
    method: str = "BANK_TRANSFER"
    reason: str = ""


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return {"paypal_mode": store.client.mode, "agent": "claude" if config.ANTHROPIC_API_KEY else "offline",
            "ledger_rows": len(store.ledger), "email": mailer.mode()}


@app.get("/api/report")
def report():
    try:
        return store.report()
    except Exception as e:
        raise HTTPException(502, f"Could not read invoices from PayPal: {e}")


@app.get("/api/invoices")
def invoices():
    try:
        return sorted(store.visible_invoices(), key=lambda i: i["number"] or "")
    except Exception as e:
        raise HTTPException(502, f"Could not read invoices from PayPal: {e}")


@app.post("/api/ledger/sample")
def load_sample():
    return {"ledger_rows": store.load_sample_ledger()}


@app.post("/api/chat")
def chat(body: ChatIn):
    return agent.chat(body.message, body.history)


@app.get("/api/actions")
def actions():
    return list(store.actions.values())


@app.post("/api/actions")
def propose(body: ActionIn):
    try:
        return store.propose(body.invoice_id, body.amount, body.method, body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/actions/{action_id}/{decision}")
def decide(action_id: str, decision: str):
    if decision not in ("approve", "reject") or action_id not in store.actions:
        raise HTTPException(404, "not found")
    try:
        return store.decide(action_id, decision == "approve")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.post("/api/ledger")
async def upload_ledger(request: Request):
    try:
        store.set_ledger_csv((await request.body()).decode("utf-8-sig"))
    except Exception as e:
        raise HTTPException(400, f"could not parse CSV (need date,amount,description): {e}")
    return {"ledger_rows": len(store.ledger)}


@app.get("/api/sample-ledger.csv", response_class=PlainTextResponse)
def sample_csv():
    return sample_data.sample_ledger_csv()


@app.get("/api/analytics")
def analytics():
    try:
        return store.analytics_report()
    except Exception as e:
        raise HTTPException(502, f"Could not build analytics: {e}")


@app.post("/api/email/draft")
def email_draft(body: EmailDraftIn):
    try:
        return store.email_draft(body.invoice_id, body.kind)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/email/send")
def email_send(body: EmailSendIn):
    try:
        return store.send_email(body.invoice_id, body.subject, body.body, body.kind)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.get("/api/outbox")
def outbox():
    return list(reversed(store.outbox))
