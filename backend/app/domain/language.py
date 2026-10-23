"""Which days a Kannada or Hindi phrase names, so a translation can be compared with the English by rules.

Seen live with Sarvam (2026-10-23): "weekday evenings" came back in Kannada as "week evening, Friday evening".
Numbers matched, the back-translation looked plausible, and customers would have been told Friday only. Comparing
the set of days each wording names catches that without asking a model.
"""

import re

from app.domain import redeem

# Monday = 0. Stems match inflected forms too (ಸೋಮವಾರದಿಂದ, ಶುಕ್ರವಾರದವರೆಗೆ, शुक्रवार को).
DAYS = {
    "kn": [("ಸೋಮವಾರ",), ("ಮಂಗಳವಾರ",), ("ಬುಧವಾರ",), ("ಗುರುವಾರ",), ("ಶುಕ್ರವಾರ",), ("ಶನಿವಾರ",), ("ಭಾನುವಾರ", "ರವಿವಾರ")],
    "hi": [("सोमवार",), ("मंगलवार",), ("बुधवार",), ("गुरुवार", "बृहस्पतिवार"), ("शुक्रवार",), ("शनिवार",), ("रविवार", "इतवार")],
}
WEEKDAYS = {"kn": ("ವಾರದ ದಿನ", "ಕೆಲಸದ ದಿನ", "ವೀಕ್‌ಡೇ", "ವೀಕ್ ಡೇ"), "hi": ("सप्ताह के दिन", "कार्यदिवस", "कार्य दिवस", "वीकडे", "वीकडेज़")}
WEEKENDS = {"kn": ("ವಾರಾಂತ್ಯ", "ವೀಕೆಂಡ್"), "hi": ("सप्ताहांत", "वीकेंड")}
# "from X to Y": Kannada marks X with -ದಿಂದ / -ರಿಂದ, Hindi puts से after it.
RANGE = {"kn": re.compile(r"^(?:ದಿಂದ|ರಿಂದ|ಇಂದ)"), "hi": re.compile(r"^\s*से(?:\s|$)")}


def days_in(text: str, lang: str) -> set[int] | None:
    """Weekday numbers a phrase names, or None when it names no day at all."""
    if lang == "en":
        return redeem.weekdays(text)
    if lang not in DAYS:
        return None
    found: set[int] = set()
    if any(w in text for w in WEEKDAYS[lang]):
        found |= {0, 1, 2, 3, 4}
    if any(w in text for w in WEEKENDS[lang]):
        found |= {5, 6}
    hits = sorted((m.start(), m.end(), i) for i, names in enumerate(DAYS[lang]) for n in names
                  for m in re.finditer(re.escape(n), text))
    for n, (_start, end, day) in enumerate(hits):
        found.add(day)
        if n + 1 < len(hits) and RANGE[lang].search(text[end:]):
            nxt = hits[n + 1][2]
            found |= {(day + k) % 7 for k in range((nxt - day) % 7 + 1)}
    return found or None


def day_mismatch(english: str, other: str, lang: str) -> str | None:
    """Why the days differ, or None. Only when the translation names days: a wording that leaves days out
    (e.g. "evenings" for a fact whose days live elsewhere) is not this check's business."""
    want, got = days_in(english, "en"), days_in(other, lang)
    if got is None or got == want:
        return None
    say = lambda ds: ", ".join(redeem.DAY_NAMES[d].title()[:3] for d in sorted(ds)) if ds else "no particular day"  # noqa: E731
    return f"It names different days from the English: {say(got)} instead of {say(want)}."


# Times of day a post may name, as hours (24h; past midnight runs on to 28). A post that says "night" for a
# 4 to 7 pm offer sends people at the wrong time. Seen in the Checker test: the model let "ರಾತ್ರಿ ಕಾಫಿ" (night coffee)
# and "रात को" pass for an evening offer.
PERIODS = {"morning": (5, 11), "breakfast": (6, 11), "brunch": (10, 13), "lunch": (12, 15), "afternoon": (12, 17),
           "evening": (16, 21), "dinner": (19, 23), "night": (20, 28), "midnight": (23, 26), "late night": (22, 28)}
_TIME_WORDS = {
    "en": {"morning": "morning", "mornings": "morning", "breakfast": "breakfast", "brunch": "brunch",
           "lunch": "lunch", "lunchtime": "lunch", "afternoon": "afternoon", "afternoons": "afternoon",
           "evening": "evening", "evenings": "evening", "dinner": "dinner", "night": "night", "nights": "night",
           "midnight": "midnight", "late night": "late night", "late-night": "late night"},
    "kn": {"ಬೆಳಗ್ಗೆ": "morning", "ಬೆಳಿಗ್ಗೆ": "morning", "ಬೆಳಗಿನ": "morning", "ಮುಂಜಾನೆ": "morning",
           "ಮಧ್ಯಾಹ್ನ": "afternoon", "ಸಂಜೆ": "evening", "ರಾತ್ರಿ": "night", "ಮಧ್ಯರಾತ್ರಿ": "midnight"},
    "hi": {"सुबह": "morning", "नाश्ता": "breakfast", "नाश्ते": "breakfast", "दोपहर": "afternoon", "शाम": "evening",
           "रात": "night", "रात्रि": "night", "आधी रात": "midnight"},
}
_EDGE = r"[A-Za-zऀ-ॿಀ-೿]"


def times_named(text: str, lang: str) -> set[str]:
    """Times of day a phrase names, in English and in the post's language (code-mixed posts use both)."""
    found = set()
    for code, words in (("en", _TIME_WORDS["en"]), (lang, _TIME_WORDS.get(lang, {}))):
        tail = rf"(?!{_EDGE})" if code == "en" else ""  # Indic words take suffixes: ರಾತ್ರಿಯ, रातें
        for w, period in words.items():
            if re.search(rf"(?<!{_EDGE}){re.escape(w)}{tail}", text, re.I):
                found.add(period)
    if found & {"midnight", "late night"}:
        found.discard("night")
    return found


def time_mismatch(text: str, lang: str, hours: tuple[int, int]) -> list[str]:
    """Times of day in the text that do not overlap the offer's hours (start, end in 24h; may cross midnight)."""
    a, b = hours if hours[1] > hours[0] else (hours[0], hours[1] + 24)
    return sorted(p for p in times_named(text, lang) if not (PERIODS[p][0] < b and a < PERIODS[p][1]))
