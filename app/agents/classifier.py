"""
Stage 3 agent: read a post and return structured fields.

With OPENAI_API_KEY set, an LLM reads the post (OpenAI Chat Completions API, JSON mode).
Without it, a keyword classifier runs, so the demo works offline.
IDs (reg no, booking, appointment, ticket) are always also pulled by regex: they are facts, not opinions.
"""
import json
import re

from openai import OpenAI

from .. import config

THEME_CODES = ["S1", "S2", "S3", "S4", "B1", "B2", "B3", "B4", "C", "X1", "O", "P"]

REG_RE = re.compile(r"\b(?:AP|AR|AS|BR|CG|CH|DL|GA|GJ|HR|HP|JH|JK|KA|KL|MP|MH|MN|ML|MZ|NL|OD|PB|PY|RJ|SK|TN|TS|TR|UK|UP|WB)"
                    r"[\s-]?\d{1,2}[\s-]?[A-Z]{0,3}[\s-]?\d{4}\b", re.I)
BOOKING_RE = re.compile(r"\b(BKG-[A-Z0-9]{5,8}|APPT-\d{4,8})\b", re.I)
TICKET_RE = re.compile(r"ticket\s*(?:id|no\.?)?\s*[:#]?\s*#?\s*(\d{5,9})", re.I)
AMOUNT_RE = re.compile(r"(?:₹|rs\.?\s?|inr\s?)\s?([\d,]+(?:\.\d+)?)\s*(lakh|lac|l\b)?", re.I)
LEGAL_RE = re.compile(r"consumer court|legal notice|legal action|police|lawyer|\bfir\b", re.I)
MONTHS_RE = re.compile(r"(\d{1,2})\s*months?", re.I)
HINGLISH_RE = re.compile(r"\b(hai|nahi|nhi|kar|ke baad|bhi|paise|gaadi|wale|ab|diya|raha|rahe|bakwas)\b", re.I)


def extract_ids(text: str) -> dict:
    ids = {}
    if m := REG_RE.search(text):
        ids["reg_no"] = re.sub(r"[\s-]", "", m.group(0)).upper()
    for m in BOOKING_RE.finditer(text):
        ref = m.group(1).upper()
        ids["booking_id" if ref.startswith("BKG") else "appointment_id"] = ref
    if m := TICKET_RE.search(text):
        ids["ticket_id"] = m.group(1)
    return ids


def extract_amount(text: str) -> float | None:
    best = None
    for num, lakh in AMOUNT_RE.findall(text):
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        if lakh:
            v *= 100000
        if v >= 100 and (best is None or v < best):   # the smallest stated sum is usually the disputed one
            best = v
    return best


def language(text: str) -> str:
    return "hinglish" if len(HINGLISH_RE.findall(text)) >= 2 else "en"


def _has(t, *words):
    return any(w in t for w in words)


def classify_rules(title: str | None, body: str, rating: int | None) -> dict:
    t = f"{title or ''} {body}".lower()
    seller = _has(t, "sold", "sell", "selling", "inspection", "auction", "listing", "valuation", "sale amount", "inspector")
    buyer = _has(t, "bought", "purchase", "booking", "delivered", "token", "warranty", "test drive")
    negative = _has(t, "not ", "no ", "never", "still", "worst", "fraud", "scam", "refund", "nahi", "bakwas")
    if rating and rating >= 4 and not negative:
        theme = "P"
    elif _has(t, "challan") and _has(t, "paid", "payment") and _has(t, "through cars24", "via cars24", "e-challan") and not _has(t, "sold"):
        theme = "C"
    elif _has(t, "added", "charges", "service fee", "processing fee") and _has(t, "price", "shown", "online"):
        theme = "B4"
    elif _has(t, " rc", "rc ", "ownership", "transfer", "registration", "driven in my name"):
        theme = "S3" if (seller or not buyer) else "B3"
    elif _has(t, "held", "holdback", "hold back", "withheld", "blocked"):
        theme = "S4"
    elif _has(t, "estimate", "offer was", "quoted", "valuation") and _has(t, "lakh", "low", "dropped", "reduced", "no reason"):
        theme = "S2"
    elif _has(t, "plan", "selling pro", "subscription", "listing fee", "auction fee", "package"):
        theme = "S1"
    elif _has(t, "non-accidental", "accident", "repaint", "odometer", "tampered", "undisclosed"):
        theme = "B1"
    elif _has(t, "warranty", "broke down", "gearbox", "clutch", "repair", "workshop", "engine"):
        theme = "B2"
    elif _has(t, "refund", "token", "booking", "charges", "fee", "deduct", "processing"):
        theme = "S1" if seller and not buyer else "B4"
    elif _has(t, "calls", "calling", "spam", "rude", "no response", "stop"):
        theme = "X1"
    else:
        theme = "O"
    role = "seller" if theme.startswith("S") else "buyer" if theme.startswith("B") else ("seller" if seller else "buyer" if buyer else "other")
    months = max([int(m) for m in MONTHS_RE.findall(t)] or [0])
    first = re.split(r"(?<=[.!?])\s", body.strip())[0]
    return {
        "theme": theme, "role": role, "amount_inr": extract_amount(body),
        "legal_risk": bool(LEGAL_RE.search(t)), "months_waiting": months,
        "summary": first[:110], "confidence": 0.7 if theme not in ("O",) else 0.4,
        "sentiment": "angry" if (rating or 3) <= 1 or "!!" in body or body.isupper() else "negative" if theme != "P" else "positive",
        "classifier": "rules",
    }


PROMPT = """You triage customer complaints about Cars24, an Indian used-car marketplace.
Read the post and answer with ONE JSON object only, no prose:
{"theme": one of S1,S2,S3,S4,B1,B2,B3,B4,C,X1,O,P,
 "role": "seller"|"buyer"|"other",
 "amount_inr": number or null (the disputed amount, not the car price),
 "legal_risk": true|false (mentions consumer court, police, lawyer, legal notice, FIR),
 "months_waiting": integer (0 if not stated),
 "summary": "max 15 words, plain English, no names",
 "sentiment": "angry"|"negative"|"neutral"|"positive",
 "confidence": 0..1}
Themes:
S1 seller paid plan/fee (Selling Pro, listing, auction fee) with no result or refund
S2 seller valuation drop after inspection, low offer vs estimate
S3 seller: RC/ownership not transferred after sale, challans or liability after handover
S4 seller: money held back after handover
B1 buyer: hidden defects, accident or odometer misrepresentation
B2 buyer: warranty denial or poor after-sales repair
B3 buyer: RC transfer delay on a bought car
B4 buyer: hidden charges, price changes, finance/insurance add-ons, booking cancellation or refund
C  challan-payment service paid through Cars24 not updated
X1 no response, spam calls, rude staff (nothing more specific)
O  other or unclear
P  positive / praise
Post title: {title}
Post rating: {rating}
Post text: {body}"""


_client = None


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL, timeout=20, max_retries=1)
    return _client


def classify_llm(title, body, rating) -> dict | None:
    if not config.OPENAI_API_KEY:
        return None
    try:
        r = _openai().chat.completions.create(
            model=config.OPENAI_MODEL,
            max_completion_tokens=300,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": PROMPT.replace("{title}", title or "-")
                       .replace("{rating}", str(rating) if rating else "-").replace("{body}", body)}])
        text = r.choices[0].message.content or ""
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        if data.get("theme") not in THEME_CODES:
            return None
        data["classifier"] = f"llm:{config.OPENAI_MODEL}"
        return data
    except Exception:
        return None


def classify(title: str | None, body: str, rating: int | None) -> dict:
    out = classify_llm(title, body, rating) or classify_rules(title, body, rating)
    out["ids"] = extract_ids(f"{title or ''} {body}")
    out["language"] = language(body)
    if out.get("amount_inr") is None:
        out["amount_inr"] = extract_amount(body)
    out["legal_risk"] = bool(out.get("legal_risk")) or bool(LEGAL_RE.search(body))
    return out
