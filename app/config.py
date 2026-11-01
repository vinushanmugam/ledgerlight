import os

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_ENV = os.getenv("PAYPAL_ENV", "sandbox")  # sandbox | live (keep sandbox for the hackathon)
USE_MOCK = os.getenv("USE_MOCK", "").lower() in ("1", "true", "yes") or not (
    PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

# Assumed PayPal fee schedule used to recognise bank deposits that arrive NET of fees.
# Defaults mirror the published US invoice rate (3.49% + $0.49); adjust to your account.
FEE_PCT = float(os.getenv("FEE_PCT", "0.0349"))
FEE_FIXED = float(os.getenv("FEE_FIXED", "0.49"))

# Days to wait before calling a PayPal-paid invoice "missing from the bank".
DEPOSIT_GRACE_DAYS = int(os.getenv("DEPOSIT_GRACE_DAYS", "3"))

# --- Email (optional). Without SMTP_* set, "sending" saves to the in-app outbox (demo mode). ---
SMTP_HOST = os.getenv("SMTP_HOST", "")            # e.g. smtp.gmail.com
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))    # 587 = STARTTLS, 465 = SSL
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")    # for Gmail use an App Password, never your normal password
EMAIL_FROM = os.getenv("EMAIL_FROM", "") or SMTP_USER
# Safety valve for demos/tests: when set, EVERY email goes to this address instead of the customer's.
EMAIL_OVERRIDE_TO = os.getenv("EMAIL_OVERRIDE_TO", "")
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Your business")
