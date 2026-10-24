"""Sign-up from one link: the owner pastes their website or Google Maps link and the form fills itself.

What can be read is read; nothing is invented. The model only points at things on the page. Every item and price
it returns must appear in the page text, or it is dropped, and the owner checks the whole form before saving.
A Google Maps link is looked up with the official Places API when a key is set (name, kind, area, phone, website,
how many photos the listing has); without a key, the name and map position in the link are looked up on
OpenStreetMap (free, no key). Google pages themselves are never scraped. When either gives a website, its menu
pages are read for items and prices. A photo of the printed menu can be read too (`menu_from_photo`).
"""

import asyncio
import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings
from app.photos import UA, UnsafeURL, _check_url
from app.reviews import fetch_pages

PAGE_HINT = re.compile(r"(menu|price|rate|services?|products?|shop|about|contact|visit|find-us|location)", re.I)
MAX_TEXT = 20_000
KINDS = ["Café", "Restaurant", "Bakery", "Sweet shop", "Salon", "Clothing store", "Grocery", "Gym", "Clinic"]


class Item(BaseModel):
    name: str = Field(description="Item or service exactly as written on the page")
    price: float = Field(gt=0, description="Price in rupees exactly as shown on the page")


class Read(BaseModel):
    name: str | None = None
    kind: str | None = Field(None, description=f"One of {KINDS}, or a short plain word if none fits")
    city: str | None = None
    locality: str | None = Field(None, description="Area, street or neighbourhood within the city")
    phone: str | None = Field(None, description="The business's mobile or WhatsApp number as written")
    offerings: list[Item] = Field(default_factory=list, description="Up to 30 items or services that show a price")


SYSTEM = """You read a small business's own website to pre-fill its sign-up form.
Only report what the text states. Leave a field null if it is not stated. Never guess a city from a phone code,
never round or convert prices, never invent items. Copy item names as written (fix only obvious capitalisation).
Prices are in Indian rupees; skip items without a clear price, and skip ranges, combos you cannot price, and
delivery-app prices. kind is what the business is (e.g. Café, Salon), not a description."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def _price_shown(price: float, text: str) -> bool:
    n = f"{price:.2f}".rstrip("0").rstrip(".")
    return re.search(rf"(?<![\d.,]){re.escape(n)}(?:\.0+)?(?![\d])", text.replace(",", "")) is not None


def checked(read: Read, text: str) -> tuple[dict[str, Any], int]:
    """Keep only what the page actually says. -> (fields, dropped items)."""
    low = _norm(text)
    out: dict[str, Any] = {}
    for f in ("name", "city", "locality"):
        v = (getattr(read, f) or "").strip()
        if v and _norm(v) in low:
            out[f] = v
    if read.kind:
        out["kind"] = next((k for k in KINDS if k.casefold() == read.kind.strip().casefold()), read.kind.strip()[:40])
    if (phone := _phone(read.phone)) and phone[3:] in re.sub(r"\D", "", text):  # a mobile, and on the page
        out["phone"] = phone
    items, seen = [], set()
    for it in read.offerings[:40]:
        key = _norm(it.name)
        if len(key) >= 2 and key in low and key not in seen and _price_shown(it.price, text):
            seen.add(key)
            items.append({"name": it.name.strip(), "price": it.price})
    out["offerings"] = items[:30]
    return out, len(read.offerings) - len(items)


def _ld_business(blocks: list[str]) -> dict[str, Any]:
    """schema.org LocalBusiness / Restaurant markup: the site states these fields itself."""
    found: dict[str, Any] = {}

    def walk(o: Any) -> None:
        if isinstance(o, list):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            if isinstance(o.get("address"), dict) and o.get("name") and not found:
                a = o["address"]
                found.update({"name": o.get("name"), "city": a.get("addressLocality"),
                              "locality": a.get("streetAddress"), "phone": o.get("telephone")})
            for v in o.values():
                walk(v)

    for b in blocks:
        try:
            walk(json.loads(b))
        except ValueError:
            continue
    return {k: v for k, v in found.items() if isinstance(v, str) and v.strip()}


def is_maps_link(link: str) -> bool:
    host = urlparse(link if "://" in link else f"https://{link}").hostname or ""
    path = urlparse(link if "://" in link else f"https://{link}").path
    return host in ("maps.app.goo.gl", "g.co") or host.startswith("maps.google.") or (
        ("google." in host or host == "goo.gl") and path.startswith("/maps"))


async def _final_url(link: str) -> str:
    """Follow a short Maps link's redirects (each hop checked) without reading the page."""
    url = link if "://" in link else f"https://{link}"
    async with httpx.AsyncClient(timeout=10) as c:
        for _ in range(6):
            await asyncio.to_thread(_check_url, url)
            r = await c.head(url, headers={"User-Agent": UA})
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            break
    return url


def coords_in_maps_url(url: str) -> tuple[float, float] | None:
    """The pin's position: `!3d<lat>!4d<lng>` (the place itself) or `@<lat>,<lng>` (the map's centre)."""
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url) or re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    return (float(m.group(1)), float(m.group(2))) if m else None


# Google place types and OpenStreetMap tags -> the sign-up form's kinds of business.
PLACE_KINDS = {"cafe": "Café", "coffee_shop": "Café", "tea_house": "Café", "restaurant": "Restaurant",
               "fast_food_restaurant": "Restaurant", "meal_takeaway": "Restaurant", "bakery": "Bakery",
               "dessert_shop": "Sweet shop", "confectionery": "Sweet shop", "candy_store": "Sweet shop",
               "beauty_salon": "Salon", "hair_salon": "Salon", "hair_care": "Salon", "barber_shop": "Salon",
               "clothing_store": "Clothing store", "grocery_store": "Grocery", "supermarket": "Grocery",
               "gym": "Gym", "fitness_center": "Gym", "doctor": "Clinic", "medical_clinic": "Clinic",
               "dental_clinic": "Clinic", "hospital": "Clinic"}
OSM_KINDS = {"cafe": "Café", "restaurant": "Restaurant", "fast_food": "Restaurant", "food_court": "Restaurant",
             "bakery": "Bakery", "pastry": "Bakery", "confectionery": "Sweet shop", "hairdresser": "Salon",
             "beauty": "Salon", "clothes": "Clothing store", "supermarket": "Grocery", "convenience": "Grocery",
             "greengrocer": "Grocery", "fitness_centre": "Gym", "sports_centre": "Gym", "clinic": "Clinic",
             "doctors": "Clinic", "dentist": "Clinic"}


def place_kind(types: list[str]) -> str | None:
    for t in types:
        if t in PLACE_KINDS:
            return PLACE_KINDS[t]
        if t.endswith("_restaurant"):
            return "Restaurant"
    return None


def name_in_maps_url(url: str) -> str | None:
    p = urlparse(url)
    if m := re.search(r"/maps/place/([^/@]+)", p.path):
        return unquote(m.group(1).replace("+", " ")).strip() or None
    q = parse_qs(p.query).get("q") or parse_qs(p.query).get("query")
    return q[0].strip() if q else None


async def _places(query: str, near: tuple[float, float] | None = None) -> dict[str, Any]:
    key = get_settings().google_maps_api_key
    if key is None:
        return {}
    fields = ",".join(f"places.{f}" for f in ("displayName", "addressComponents", "internationalPhoneNumber",
                                               "nationalPhoneNumber", "websiteUri", "primaryType", "types", "photos"))
    body: dict[str, Any] = {"textQuery": query, "maxResultCount": 1}
    if near:
        body["locationBias"] = {"circle": {"center": {"latitude": near[0], "longitude": near[1]}, "radius": 500.0}}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://places.googleapis.com/v1/places:searchText",
                         headers={"X-Goog-Api-Key": key.get_secret_value(), "X-Goog-FieldMask": fields}, json=body)
    places = r.json().get("places") if r.status_code == 200 else None
    if not places:
        return {}
    p = places[0]
    comp = {t: c.get("longText") for c in p.get("addressComponents") or [] for t in c.get("types") or []}
    return {k: v for k, v in {
        "name": (p.get("displayName") or {}).get("text"),
        "kind": place_kind([p.get("primaryType") or "", *(p.get("types") or [])]),
        "city": comp.get("locality") or comp.get("administrative_area_level_3"),
        "locality": comp.get("sublocality_level_1") or comp.get("sublocality") or comp.get("neighborhood"),
        "phone": p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber"),
        "website": p.get("websiteUri"),
        "photos_found": len(p.get("photos") or []),
    }.items() if v}


async def _osm(name: str, near: tuple[float, float] | None) -> dict[str, Any]:
    """OpenStreetMap's Nominatim (free, no key; one lookup per sign-up): the place by name near the pin."""
    params: dict[str, Any] = {"q": name, "format": "jsonv2", "addressdetails": 1, "extratags": 1, "limit": 1,
                              "countrycodes": "in"}
    if near:
        d = 0.01  # about a kilometre around the pin
        params |= {"viewbox": f"{near[1] - d},{near[0] + d},{near[1] + d},{near[0] - d}", "bounded": 1}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://nominatim.openstreetmap.org/search", params=params,
                            headers={"User-Agent": "Counterpart sign-up (small business marketing)"})
        found = r.json() if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return {}
    if not found:
        return {}
    p = found[0]
    a, x = p.get("address") or {}, p.get("extratags") or {}
    return {k: v for k, v in {
        "kind": OSM_KINDS.get(p.get("type") or ""),
        "city": a.get("city") or a.get("town") or a.get("village") or a.get("state_district"),
        "locality": a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or a.get("road"),
        "phone": x.get("phone") or x.get("contact:phone") or x.get("contact:mobile"),
        "website": x.get("website") or x.get("contact:website"),
    }.items() if isinstance(v, str) and v.strip()}


def _phone(raw: str | None) -> str | None:
    """Only an Indian mobile can take WhatsApp claims; landlines and toll-free numbers are left for the owner. A
    landline is written with its STD code first ("080 2663 1234"), which a mobile never is."""
    if re.match(r"^\s*\(?0\d{2,4}\)?[\s-]", raw or ""):
        return None
    digits = re.sub(r"\D", "", raw or "")
    prefix, last = digits[:-10], digits[-10:]
    return "+91" + last if prefix in ("", "0", "91") and re.fullmatch(r"[6-9]\d{9}", last) else None


async def read_link(router: Any, link: str) -> dict[str, Any]:
    """-> the fields the form can use, plus `from` (what was read) and `notes` for the owner."""
    link = link.strip()
    notes: list[str] = []
    out: dict[str, Any] = {"offerings": []}
    website = link
    if is_maps_link(link):
        final = await _final_url(link)
        name, near = name_in_maps_url(final), coords_in_maps_url(final)
        place = await _places(name or final, near) if (name or "/maps" in final) else {}
        source = "your Google Maps listing"
        if not place and name:
            place = {"name": name, **await _osm(name, near)}
            source = "the name in your Maps link and OpenStreetMap"
        if not place:
            raise UnsafeURL("Could not read that Maps link. Paste your website instead, or fill the form yourself.")
        place["phone"] = _phone(place.get("phone"))
        got = [label for k, label in (("name", "name"), ("kind", "kind of business"), ("locality", "area"),
                                      ("city", "city"), ("phone", "phone"), ("website", "website")) if place.get(k)]
        notes.append(f"From {source}: {', '.join(got)}.")
        if n := place.pop("photos_found", 0):
            out["photos_found"] = n
            notes.append(f"Your Google listing has {n} photos. They are added to your photo library after you "
                         "save (with credit to the photographer); remove any you don't want on the Photos page.")
        elif not get_settings().google_maps_api_key:
            notes.append("Google Maps photos and details need a Google Maps key on this server. Add your photos "
                         "below, or your website.")
        out.update({k: v for k, v in place.items() if v and k != "website"})
        website = place.get("website")
        if website:
            out["website"] = website
    else:
        out["website"] = link if "://" in link else f"https://{link}"
    if website:
        try:
            text, ld = await fetch_pages(website, PAGE_HINT, max_pages=4)
        except (UnsafeURL, httpx.HTTPError):
            if not out.get("name"):
                raise UnsafeURL("Could not open that website. Check the address, or fill the form yourself.") from None
            text, ld = "", []
        marked = _ld_business(ld)
        if text.strip():
            result, _ = await router.chat_json(
                "verification",
                [{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": (text + ("\n\nThe site's own markup: " + json.dumps(marked) if marked else ""))[:MAX_TEXT]}],
                Read, temperature=0)
            fields, dropped = checked(result, text + "\n" + " ".join(marked.values()))
            for k, v in fields.items():
                if v and not out.get(k):
                    out[k] = v
            if dropped:
                notes.append(f"Left out {dropped} item{'s' if dropped != 1 else ''} whose price was not clearly on the page.")
        if any("ಀ" <= ch <= "೿" for ch in text):
            out["languages"] = ["en", "kn"] + (["hi"] if any("ऀ" <= ch <= "ॿ" for ch in text) else [])
        elif any("ऀ" <= ch <= "ॿ" for ch in text):
            out["languages"] = ["en", "hi"]
    if out["offerings"]:
        notes.append(f"Found {len(out['offerings'])} items with prices. Check them, and add what you pay for each if you like.")
    return {**out, "notes": notes}


# ------------------------------------------------------------------ the menu, spoken


class SpokenItem(BaseModel):
    name: str = Field(description="The item in English letters, as Indians write it (e.g. 'Masala Dosa')")
    price: float = Field(gt=0, description="Price in rupees as said, in digits")
    said: str | None = Field(None, description="The item's name as spoken, in its own script, if not English")


class Spoken(BaseModel):
    items: list[SpokenItem] = Field(default_factory=list)


SPOKEN_SYSTEM = """The owner of a small Indian business read their menu or price list aloud. You get what they said
(possibly Kannada or Hindi) and an English translation of it. List every item they gave a price for, in the order
said. Prices are rupees; write spoken numbers ("ಇಪ್ಪತ್ತೈದು", "pachees", "twenty five") as digits. Never invent an
item or a price, never round; skip items said without a price. Reply with JSON {"items": [{"name", "price", "said"}]}."""

_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯०१२३४५६७८९", "01234567890123456789")


def spoken_checked(found: Spoken, said: str, english: str | None) -> list[dict[str, Any]]:
    """Each item, with check=True when its price is not written as digits in what was said or in the English
    translation (spoken number words): the owner confirms those on the review page."""
    heard = f"{said} {english or ''}".translate(_DIGITS)
    out, seen = [], set()
    for it in found.items[:40]:
        key = _norm(it.name)
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        out.append({"name": it.name.strip()[:80], "price": it.price, "said": it.said,
                    "check": not _price_shown(it.price, heard)})
    return out


async def menu_from_speech(router: Any, said: str, language: str, english: str | None) -> list[dict[str, Any]]:
    found, _ = await router.chat_json(
        "reasoning", [{"role": "system", "content": SPOKEN_SYSTEM},
                      {"role": "user", "content": json.dumps({"language": language, "said": said,
                                                              "english": english}, ensure_ascii=False)}],
        Spoken, temperature=0)
    return spoken_checked(found, said, english)


# ------------------------------------------------------------------ the menu, photographed


MENU_PHOTO_SYSTEM = """This is a photo of a small Indian business's printed menu, price list or rate card. List every
item or service with a clearly printed price, in the order printed. Copy names as printed (English letters; for an
item printed only in Kannada or Hindi, write it as Indians would in English letters and put the printed name in
`said`). Prices are rupees, as digits; never invent, round or guess an item or a price, skip anything unreadable,
price ranges and items without a price. Reply with JSON {"items": [{"name", "price", "said"}]}."""


async def menu_from_photo(router: Any, data_url: str) -> list[dict[str, Any]]:
    """Every item comes back with check=True: a price read off a photo cannot be checked against text, so the
    owner confirms each one on the review page."""
    found, _ = await router.chat_json(
        "vision", [{"role": "system", "content": MENU_PHOTO_SYSTEM},
                   {"role": "user", "content": [{"type": "text", "text": "The menu:"},
                                                {"type": "image_url", "image_url": {"url": data_url}}]}],
        Spoken, temperature=0)
    out, seen = [], set()
    for it in found.items[:60]:
        key = _norm(it.name)
        if len(key) >= 2 and key not in seen:
            seen.add(key)
            out.append({"name": it.name.strip()[:80], "price": it.price, "said": it.said, "check": True})
    return out
