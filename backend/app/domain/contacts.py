"""A business's own customer list, pasted by the owner: phone numbers made ready for wa.me, and the fixed words of the
messages the owner sends from their own WhatsApp (a personal code, then a review link). No I/O, no model."""

import re
from typing import Any
from urllib.parse import quote

PHONE = re.compile(r"\+?\d[\d\s().-]{7,18}\d")
LANG_WORDS = {"kannada": "kn", "ಕನ್ನಡ": "kn", "hindi": "hi", "हिंदी": "hi", "english": "en"}

# Same checked words as the WhatsApp bot (channels/whatsapp.TEXT and ASK_REVIEW); only "tell us here" is new.
INVITE = {
    "your_code": {"en": "Your code", "kn": "ನಿಮ್ಮ ಕೋಡ್", "hi": "आपका कोड"},
    "show": {"en": "Show it at the counter", "kn": "ಕೌಂಟರ್‌ನಲ್ಲಿ ತೋರಿಸಿ", "hi": "काउंटर पर दिखाएँ"},
    "qr": {"en": "QR code", "kn": "QR ಕೋಡ್", "hi": "QR कोड"},
}
REVIEW = {
    "en": "Thanks for coming to {name}! How was it? Tell us here: {link}",
    "kn": "{name}ಗೆ ಬಂದಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು! ಹೇಗಿತ್ತು? ಇಲ್ಲಿ ತಿಳಿಸಿ: {link}",
    "hi": "{name} आने के लिए धन्यवाद! कैसा लगा? यहाँ बताइए: {link}",
}
STOP_LINE = "Reply STOP if you don't want offers from us."


def phone(text: str) -> str | None:
    """-> digits with the country code (what wa.me takes), or None. A bare 10-digit Indian mobile gets 91."""
    plus = text.strip().startswith("+")
    d = re.sub(r"\D", "", text)
    if plus:
        return d if 10 <= len(d) <= 15 else None
    if len(d) == 11 and d[0] == "0":
        d = d[1:]
    if len(d) == 10 and d[0] in "6789":
        return "91" + d
    if len(d) == 12 and d.startswith("91") and d[2] in "6789":
        return d
    return None  # anything else needs its +country code, rather than a guess


def parse(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """One customer per line, in any order: "Asha, 98450 12345", "+44 7700 900123 Tom kannada", a CSV row.
    -> (customers, lines that had no usable number). The same number twice keeps the first line."""
    out: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = PHONE.search(line)
        p = phone(m.group(0)) if m else None
        if not p:
            if m or any(ch.isdigit() for ch in line):
                skipped.append(line.strip())
            continue  # a header row or a note
        rest = line[:m.start()] + " " + line[m.end():]
        words = [w for w in re.split(r"[\s,;|\t]+", rest) if w]
        lang = next((LANG_WORDS[w.lower()] for w in words if w.lower() in LANG_WORDS), None)
        name = " ".join(w for w in words if w.lower() not in LANG_WORDS and not w.isdigit()).strip(" -:\"'")
        out.setdefault(p, {"phone": p, "name": name[:80] or None, "language": lang})
    return list(out.values()), skipped


def wa_link(number: str, text: str) -> str:
    return f"https://wa.me/{number}?text={quote(text)}"


def invite_text(business: str, headline: str | None, offer: list[str], code: str, base: str, lang: str) -> str:
    t = {k: v.get(lang, v["en"]) for k, v in INVITE.items()}
    return "\n".join([f"*{business}*", *([headline] if headline else []), *offer, "",
                      f"{t['your_code']}: *{code}*", f"{t['show']}. {t['qr']}: {base}/c/{code}", "", STOP_LINE])


def review_text(business: str, code: str, base: str, lang: str) -> str:
    return REVIEW.get(lang, REVIEW["en"]).format(name=business, link=f"{base}/c/{code}")
