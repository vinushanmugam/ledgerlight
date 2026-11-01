"""Customer payment-reminder emails: deterministic drafts + SMTP send (or demo-mode outbox)."""
import smtplib
import ssl
from email.message import EmailMessage

from . import config

KINDS = {"OVERDUE", "PARTIAL", "DUPLICATE_PAYMENT", "OVERPAID"}


def money(n: float) -> str:
    return f"${n:,.2f}"


def mode() -> str:
    return "smtp" if (config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD) else "demo"


def recipient(invoice_email: str) -> tuple[str, bool]:
    """(address to use, redirected?). The override protects real customers during demos."""
    if config.EMAIL_OVERRIDE_TO:
        return config.EMAIL_OVERRIDE_TO, True
    return invoice_email, False


def build_draft(kind: str, f: dict) -> tuple[str, str]:
    """f is a reconciliation finding. All amounts come from the engine, never typed by hand."""
    inv, num, cust, amt = f["invoice"], f["invoice_number"], f["customer"], f["amount"]
    me = config.BUSINESS_NAME
    hello = f"Hello {cust} team,"
    sign = f"Thank you,\n{me}"
    if kind == "OVERDUE":
        subject = f"Invoice {num}: {money(amt)} past due"
        body = (f"{hello}\n\nI'm following up on invoice {num} for {money(inv['total'])}, which was due on "
                f"{inv['due_date']}. Our records show {money(amt)} still outstanding.\n\n"
                f"Could you let me know when we can expect payment? If it has already been sent, please reply with "
                f"the date and method so I can trace it.\n\n{sign}")
    elif kind == "PARTIAL":
        subject = f"Invoice {num}: {money(amt)} balance remaining"
        body = (f"{hello}\n\nThank you for your recent payment on invoice {num}. The invoice total is "
                f"{money(inv['total'])} and we have received a partial payment, leaving {money(amt)} outstanding.\n\n"
                f"Could you let me know when the remaining balance will be paid? Please reply if anything about the "
                f"invoice needs clarifying.\n\n{sign}")
    elif kind == "DUPLICATE_PAYMENT":
        subject = f"Invoice {num}: possible duplicate payment of {money(amt)}"
        body = (f"{hello}\n\nIt looks like invoice {num} ({money(inv['total'])}) may have been paid twice, which "
                f"would leave an extra {money(amt)} on our side.\n\nCould you confirm on your end? If so, tell me "
                f"whether you'd prefer a refund or a credit toward your next invoice.\n\n{sign}")
    elif kind == "OVERPAID":
        subject = f"Invoice {num}: payment exceeds invoice by {money(amt)}"
        body = (f"{hello}\n\nThank you for paying invoice {num}. Your payment exceeds the invoice total of "
                f"{money(inv['total'])} by {money(amt)}.\n\nWould you like the difference refunded, or applied as a "
                f"credit to your next invoice?\n\n{sign}")
    else:
        raise ValueError(f"no email template for {kind}")
    return subject, body


def send(to: str, subject: str, body: str) -> str:
    """Returns 'sent' (real SMTP) or 'saved' (demo mode, nothing leaves the app)."""
    if "@" not in to or " " in to:
        raise ValueError(f"'{to}' does not look like an email address")
    if mode() == "demo":
        return "saved"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.EMAIL_FROM, to, subject
    msg.set_content(body)
    try:
        if config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, 465, timeout=20, context=ssl.create_default_context()) as s:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg)
    except Exception as e:
        raise RuntimeError(f"Email could not be sent ({type(e).__name__}): {e}")
    return "sent"
