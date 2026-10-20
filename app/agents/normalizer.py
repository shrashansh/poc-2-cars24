"""Stage 2 agent: clean the text and mask personal data before it is shown in the dashboard."""
import hashlib
import re

PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def mask(text: str) -> str:
    text = PHONE_RE.sub(lambda m: m.group(0)[:3] + "•••••" + m.group(0)[-2:], text)
    return EMAIL_RE.sub(lambda m: m.group(0)[0] + "•••@" + m.group(0).split("@")[1], text)


def content_hash(title, body, rating) -> str:
    return hashlib.sha256(f"{title}|{body}|{rating}".encode()).hexdigest()


def tokens(text: str) -> set[str]:
    stop = {"the", "and", "my", "to", "of", "is", "a", "in", "it", "i", "for", "was", "not", "no", "still", "cars24",
            "after", "with", "on", "me", "this", "that", "they", "have", "has", "been", "from", "your", "you", "are"}
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in stop}


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / max(1, len(ta | tb))
