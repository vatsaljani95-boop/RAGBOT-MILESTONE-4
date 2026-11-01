from __future__ import annotations

import re

EDUCATIONAL_URL = "https://groww.in/mutual-funds/amc/hdfc-mutual-funds"

PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.I)
AADHAAR_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
PHONE_RE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
FOLIO_RE = re.compile(r"\b(?:folio|account(?:\s+number)?)\s*[:#-]?\s*\d{6,}\b", re.I)
OTP_RE = re.compile(r"\botp\b|\b\d{4,8}\s*otp\b|\botp\s*\d{4,8}\b", re.I)

ADVICE_RE = re.compile(
    r"\b(should i|shall i|good time|recommend|advice|advise|buy or sell|"
    r"is it (a )?good|worth (buying|investing)|portfolio)\b",
    re.I,
)
BUY_SELL_RE = re.compile(r"\b(buy|sell|invest in)\b", re.I)
RETURNS_RE = re.compile(
    r"\b(return[s]?|cagr|outperform|vs nifty|versus nifty|1y|3y|5y|"
    r"historic returns|performance)\b",
    re.I,
)


def screen_query(text: str) -> dict:
    raw = text or ""
    stripped = raw.strip()
    if not stripped:
        return {
            "action": "refuse",
            "intent": "empty",
            "reason": "empty",
            "persist_query": False,
            "message": "Please ask a factual question about one of the listed HDFC schemes.",
            "source_url": None,
        }

    pii_hit = None
    if PAN_RE.search(stripped):
        pii_hit = "PAN"
    elif AADHAAR_RE.search(stripped):
        pii_hit = "Aadhaar"
    elif EMAIL_RE.search(stripped):
        pii_hit = "email"
    elif FOLIO_RE.search(stripped):
        pii_hit = "account"
    elif OTP_RE.search(stripped):
        pii_hit = "OTP"
    elif PHONE_RE.search(stripped):
        pii_hit = "phone"

    if pii_hit:
        return {
            "action": "refuse",
            "intent": "pii",
            "reason": f"pii:{pii_hit}",
            "persist_query": False,
            "message": "I cannot accept personal identifiers (PAN, Aadhaar, account numbers, OTP, email, or phone). Ask a scheme fact without personal data.",
            "source_url": None,
        }

    if ADVICE_RE.search(stripped) or (
        BUY_SELL_RE.search(stripped) and re.search(r"\b(should|worth|good|recommend)\b", stripped, re.I)
    ):
        return {
            "action": "refuse",
            "intent": "advice",
            "reason": "advice",
            "persist_query": True,
            "message": "Facts-only. I cannot say whether you should buy or sell. See the official scheme page for published facts.",
            "source_url": EDUCATIONAL_URL,
        }

    if RETURNS_RE.search(stripped) and re.search(
        r"\b(compare|vs|versus|calculate|computed?|cagr|outperform)\b", stripped, re.I
    ):
        return {
            "action": "retrieve",
            "intent": "returns",
            "reason": "returns_no_math",
            "persist_query": True,
            "message": "I do not calculate or compare returns. I can only point to official published facts if they are in this corpus.",
            "source_url": None,
        }

    return {
        "action": "retrieve",
        "intent": "fact",
        "reason": None,
        "persist_query": True,
        "message": None,
        "source_url": None,
    }
