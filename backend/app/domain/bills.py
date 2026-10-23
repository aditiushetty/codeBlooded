"""Match a payment statement to the codes redeemed at the counter, so the owner sees real sales per post without
typing every bill. Pure: the statement text and the redemptions are passed in.

Works with the CSV export of most UPI apps, card machines and bank statements: it looks for a date (with or
without a separate time column), an amount (or a credit column) and a note. Debits are skipped.

A payment is matched to a redemption
  1. by code: the customer's or staff's payment note contains the code (certain), else
  2. by time: it is the only payment within MAX_GAP minutes of the redemption, and no other redemption is closer
     to it (likely). Several payments close together are left unmatched rather than guessed.
"""

import csv
import io
import re
from datetime import datetime, timedelta
from typing import Any

MAX_GAP = timedelta(minutes=20)
CODE = re.compile(r"\b[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{6,7}\b")

_DATE = ("date & time", "date and time", "transaction date", "txn date", "date", "value date", "timestamp",
         "created at", "time stamp")
_TIME = ("time", "transaction time", "txn time")
_AMOUNT = ("amount", "amount (inr)", "amount(inr)", "transaction amount", "txn amount", "credit", "credit amount",
           "cr amount", "deposit", "deposits", "paid in", "received")
_DEBIT = ("debit", "debit amount", "dr amount", "withdrawal", "withdrawals", "paid out")
_TYPE = ("type", "dr/cr", "cr/dr", "transaction type", "txn type", "status")
_NOTE = ("note", "notes", "remarks", "narration", "description", "details", "particulars", "message", "comment",
         "transaction details", "payment note")
_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p", "%d/%m/%Y %I:%M:%S %p", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
            "%d-%m-%Y %I:%M %p", "%d %b %Y %H:%M", "%d %b %Y %I:%M %p", "%d %b %Y, %I:%M %p", "%d %b %Y, %H:%M",
            "%b %d, %Y %I:%M %p", "%b %d, %Y, %I:%M %p", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %I:%M %p",
            "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%b %d, %Y")


def _col(headers: list[str], names: tuple[str, ...]) -> int | None:
    low = [h.strip().casefold() for h in headers]
    for n in names:
        if n in low:
            return low.index(n)
    for n in names:  # "Amount (Rs.)", "Transaction Date (IST)"
        for i, h in enumerate(low):
            if h.startswith(n):
                return i
    return None


def _when(text: str) -> tuple[datetime | None, bool]:
    """-> (datetime, has a time of day). Month names and am/pm are read in any case."""
    t = re.sub(r"\s+", " ", text.strip().replace("\u202f", " "))
    t = re.sub(r"\s*IST$", "", t, flags=re.I)
    t = re.sub(r"(?<=\d)\s*([ap])\.?m\.?$", lambda m: f" {m.group(1).upper()}M", t, flags=re.I)
    for f in _FORMATS:
        try:
            d = datetime.strptime(t, f)
        except ValueError:
            continue
        return d, "%H" in f or "%I" in f
    return None, False


def _amount(text: str) -> float | None:
    t = text.replace(",", "").replace("₹", "").replace("Rs.", "").replace("INR", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group()) if m else None


def parse(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """-> (payments [{at, has_time, amount, note, row}], problems)."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    # Statements often start with a few lines about the account; the header is the first row naming a date column.
    head = next((i for i, r in enumerate(rows[:30]) if _col(r, _DATE) is not None and
                 (_col(r, _AMOUNT) is not None or _col(r, _DEBIT) is not None)), None)
    if head is None:
        return [], ["Could not find the header row: the file needs a date column and an amount (or credit) column."]
    headers = rows[head]
    di, ti, ai = _col(headers, _DATE), _col(headers, _TIME), _col(headers, _AMOUNT)
    dbi, tyi, ni = _col(headers, _DEBIT), _col(headers, _TYPE), _col(headers, _NOTE)
    if ti == di:
        ti = None
    out, skipped = [], 0
    for n, r in enumerate(rows[head + 1:], start=head + 2):
        def cell(i: int | None, r: list[str] = r) -> str:
            return r[i].strip() if i is not None and i < len(r) else ""

        raw = cell(di) + (f" {cell(ti)}" if ti is not None and cell(ti) else "")
        at, has_time = _when(raw)
        amount = _amount(cell(ai)) if ai is not None else None
        kind = cell(tyi).casefold()
        if amount is None and dbi is not None and _amount(cell(dbi)):
            continue  # a debit-only row
        if at is None or amount is None:
            skipped += 1
            continue
        if amount < 0 or kind in ("dr", "debit", "debited", "paid", "sent") or "fail" in kind:
            continue
        if amount == 0:
            continue
        out.append({"at": at, "has_time": has_time, "amount": round(amount, 2), "note": cell(ni), "row": n})
    problems = [f"Skipped {skipped} row(s) without a readable date or amount."] if skipped else []
    if out and not any(p["has_time"] for p in out):
        problems.append("The statement has dates but no times, so payments can only be matched by a code in the "
                        "payment note.")
    return out, problems


def match(payments: list[dict[str, Any]], redemptions: list[dict[str, Any]]) -> dict[str, Any]:
    """redemptions: [{code, post_code, at (local naive datetime), bill_amount}]. Only those without a bill are
    matched. -> {matches: [{code, amount, at, how, gap_min, row}], unmatched_codes, totals}."""
    open_ = [r for r in redemptions if r.get("bill_amount") is None]
    used: set[int] = set()
    matches = []
    by_code = {c: r for r in open_ for c in (r["code"], r.get("post_code")) if c}
    for i, p in enumerate(payments):  # 1. a code in the payment note
        for c in CODE.findall(p["note"].upper()):
            r = by_code.get(c)
            if r and r["code"] not in {m["code"] for m in matches}:
                matches.append(_m(r, p, "code"))
                used.add(i)
                break
    done = {m["code"] for m in matches}
    timed = [(i, p) for i, p in enumerate(payments) if p["has_time"] and i not in used]
    waiting = [r for r in open_ if r["code"] not in done]
    # 2. by time, only when it is one payment for one redemption: each has nobody else within MAX_GAP
    for r in waiting:
        near = [(i, p) for i, p in timed if abs(p["at"] - r["at"]) <= MAX_GAP and i not in used]
        if len(near) != 1:
            continue
        i, p = near[0]
        if sum(abs(p["at"] - o["at"]) <= MAX_GAP for o in waiting) == 1:
            matches.append(_m(r, p, "time"))
            used.add(i)
    total = round(sum(p["amount"] for p in payments), 2)
    with_code = round(sum(m["amount"] for m in matches), 2)
    matched = {m["code"] for m in matches}
    return {"matches": matches, "unmatched_codes": [r["code"] for r in open_ if r["code"] not in matched],
            "totals": {"payments": len(payments), "sales": total, "matched": len(matches), "matched_sales": with_code,
                       "share": round(with_code / total, 4) if total else None,
                       "already_had_bill": len(redemptions) - len(open_)}}


def _m(r: dict[str, Any], p: dict[str, Any], how: str) -> dict[str, Any]:
    return {"code": r["code"], "amount": p["amount"], "at": p["at"].isoformat(timespec="minutes"), "how": how,
            "gap_min": round(abs((p["at"] - r["at"]).total_seconds()) / 60) if p["has_time"] else None, "row": p["row"],
            "note": p["note"][:80]}
