"""WhatsApp message templates, drafted from a live post and checked against Meta's rules before submitting.

Outside the free 24-hour window a business may only message a customer with a template Meta has approved. A
template rejected for a formatting rule costs a day, so the rules Meta documents are checked here first:
  - name: lowercase letters, digits and underscores, at most 512 characters
  - body: required, at most 1024 characters; variables are {{1}}, {{2}}, ... in order, each with an example,
    never at the very start or end of the body and never two side by side
  - footer: at most 60 characters, no variables
The body is the post's own checked text (headline, message and the locked offer wording); the only variable is
the customer's tracked link, filled in per message. Pure: no I/O.
"""

import re
from typing import Any

LANGS = {"en": "en", "kn": "kn", "hi": "hi"}  # Meta's codes for the business's languages
FOOTER = {"en": "Reply STOP to stop offers", "kn": "ಆಫರ್ ಬೇಡವೆಂದರೆ STOP ಎಂದು ಉತ್ತರಿಸಿ",
          "hi": "ऑफ़र बंद करने के लिए STOP लिखें"}
CLOSE = {"en": "Get your code here: {{1}} and show it at the counter.",
         "kn": "ನಿಮ್ಮ ಕೋಡ್ ಇಲ್ಲಿ ಪಡೆಯಿರಿ: {{1}} ಮತ್ತು ಕೌಂಟರ್‌ನಲ್ಲಿ ತೋರಿಸಿ.",
         "hi": "अपना कोड यहाँ पाएँ: {{1}} और काउंटर पर दिखाएँ।"}
_VAR = re.compile(r"\{\{\s*(\d+)\s*\}\}")
MAX_BODY, MAX_FOOTER, MAX_NAME = 1024, 60, 512


def name_for(business_slug: str, post_code: str, language: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", business_slug.casefold()).strip("_")
    return f"{base}_{post_code.casefold()}_{language}"[:MAX_NAME]


def draft(*, business_slug: str, post_code: str, language: str, headline: str, body: str, offer: list[str],
          link: str) -> dict[str, Any]:
    lang = language if language in LANGS else "en"
    lines = [f"*{headline.strip()}*" if headline.strip() else "", body.strip(), "", *[o.strip() for o in offer if o],
             "", CLOSE[lang]]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return {"name": name_for(business_slug, post_code, lang), "language": LANGS[lang], "category": "MARKETING",
            "body": text, "footer": FOOTER[lang], "example": [link]}


def problems(t: dict[str, Any]) -> list[str]:
    out = []
    if not re.fullmatch(r"[a-z0-9_]{1,512}", t.get("name") or ""):
        out.append("The name may use only lowercase letters, digits and underscores.")
    body = t.get("body") or ""
    if not body.strip():
        out.append("The message is empty.")
    if len(body) > MAX_BODY:
        out.append(f"The message is {len(body)} characters; WhatsApp allows {MAX_BODY}.")
    nums = [int(n) for n in _VAR.findall(body)]
    if nums != list(range(1, len(nums) + 1)):
        out.append("Variables must be numbered {{1}}, {{2}}, ... in order, each used once.")
    if len(t.get("example") or []) != len(nums):
        out.append(f"Each variable needs an example value ({len(nums)} variable(s), "
                   f"{len(t.get('example') or [])} example(s)).")
    stripped = body.strip(" \n*_~.!?,:;")
    if _VAR.match(stripped) or re.search(r"\{\{\s*\d+\s*\}\}$", stripped):
        out.append("A variable cannot be the first or last thing in the message; put words around it.")
    if re.search(r"\}\}[\s\W]{0,3}\{\{", body):
        out.append("Two variables cannot sit side by side.")
    footer = t.get("footer") or ""
    if len(footer) > MAX_FOOTER:
        out.append(f"The footer is {len(footer)} characters; WhatsApp allows {MAX_FOOTER}.")
    if _VAR.search(footer):
        out.append("The footer cannot contain variables.")
    if t.get("language") not in LANGS.values():
        out.append(f"Unsupported language {t.get('language')!r}.")
    return out


def components(t: dict[str, Any]) -> list[dict[str, Any]]:
    """The template in the shape Meta's message_templates endpoint takes."""
    body: dict[str, Any] = {"type": "BODY", "text": t["body"]}
    if t.get("example"):
        body["example"] = {"body_text": [list(t["example"])]}
    out = [body]
    if t.get("footer"):
        out.append({"type": "FOOTER", "text": t["footer"]})
    return out


STATUS = {"APPROVED": "approved", "REJECTED": "rejected", "PENDING": "pending", "IN_APPEAL": "pending",
          "PAUSED": "paused", "DISABLED": "disabled", "PENDING_DELETION": "disabled", "DELETED": "disabled",
          "FLAGGED": "approved", "REINSTATED": "approved"}
