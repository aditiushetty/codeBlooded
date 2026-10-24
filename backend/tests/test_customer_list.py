"""The business's own customer list without the WhatsApp API: paste with consent, a personal code per customer, the
prepared wa.me message, the counter, then a review link that becomes a verified visit review."""

from urllib.parse import unquote

from app.db import connection, fetch_one
from app.domain import contacts
from tests.test_channels import live_post


def test_numbers_are_made_ready_for_wa_me_or_refused():
    assert contacts.phone("98450 12345") == "919845012345"
    assert contacts.phone("098450-12345") == "919845012345"
    assert contacts.phone("+91 98450 12345") == "919845012345"
    assert contacts.phone("+44 7700 900123") == "447700900123"
    assert contacts.phone("080 2345 678") is None  # a landline or a short number: no guessing
    rows, skipped = contacts.parse("name,phone\nAsha, 98450 12345\n98450 12345 again\nTom +44 7700 900123 kannada\nRavi 12345")
    assert [(r["name"], r["phone"], r["language"]) for r in rows] == [
        ("Asha", "919845012345", None), ("Tom", "447700900123", "kn")]
    assert skipped == ["Ravi 12345"]


async def test_existing_customers_get_codes_on_whatsapp_then_a_review_link(client, scripted):
    from tests.fakes import text

    _, post = await live_post("whatsapp")
    paste = {"text": "Asha, 98450 11111\nRavi +44 7700 900111 kannada\nnot a number 123", "consent": False}
    assert (await client.post("/api/businesses/kaapi-kone/contacts", json=paste)).status_code == 409  # consent first
    r = (await client.post("/api/businesses/kaapi-kone/contacts", json={**paste, "consent": True})).json()
    assert r == {"added": 2, "updated": 0, "skipped": ["not a number 123"]}
    listed = (await client.get("/api/businesses/kaapi-kone/contacts")).json()["contacts"]
    asha = next(c for c in listed if c["phone"] == "919845011111")
    ravi = next(c for c in listed if c["phone"] == "447700900111")

    async with connection() as conn:
        campaign = str((await fetch_one(conn, "select campaign_id from touchpoints where code = %s", (post,)))["campaign_id"])
    ids = [asha["id"], ravi["id"]]
    assert (await client.post(f"/api/campaigns/{campaign}/invites", json={"contact_ids": ids})).json()["made"] == 2
    assert (await client.post(f"/api/campaigns/{campaign}/invites", json={"contact_ids": ids})).json()["made"] == 0  # same code kept
    async with connection() as conn:  # made by the owner, not asked for: the campaign's "claimed" does not move
        assert (await fetch_one(conn, "select count(*)::int as n from outcome_events where touchpoint_code = %s "
                                      "and type = 'click'", (post,)))["n"] == 0

    rows = {r["phone"]: r for r in (await client.get(f"/api/campaigns/{campaign}/invites")).json()["invites"]}
    a, k = rows["919845011111"], rows["447700900111"]
    assert a["status"] == "ready" and a["message"]["kind"] == "invite"
    assert a["message"]["link"].startswith("https://wa.me/919845011111?text=")
    sent = unquote(a["message"]["link"].split("text=")[1])
    assert f"*{a['code']}*" in sent and "15% off" in sent and f"/c/{a['code']}" in sent and contacts.STOP_LINE in sent
    assert "ನಿಮ್ಮ ಕೋಡ್" in k["message"]["text"]  # Ravi reads Kannada

    assert (await client.post(f"/api/claims/{a['code']}/sent", json={"kind": "invite"})).status_code == 200
    await client.post("/api/counter/redeem", json={"code": a["code"], "outside_rules": "test"})
    a = next(r for r in (await client.get(f"/api/campaigns/{campaign}/invites")).json()["invites"] if r["code"] == a["code"])
    assert a["status"] == "came_in" and a["message"]["kind"] == "review" and f"/c/{a['code']}" in a["message"]["text"]

    scripted.push(text('{"sentiment": 0.7, "themes": ["filter_coffee"], "english": null}'))
    r = await client.post(f"/api/public/claims/{a['code']}/review", json={"rating": 5, "comment": "Lovely", "language": "en"})
    assert r.status_code == 200
    data = (await client.get(f"/api/campaigns/{campaign}/invites")).json()
    assert data["counts"] == {"ready": 1, "sent": 0, "came_in": 0, "reviewed": 1}
    listed = {c["phone"]: c for c in (await client.get("/api/businesses/kaapi-kone/contacts")).json()["contacts"]}
    assert listed["919845011111"]["visits"] == 1 and listed["919845011111"]["reviews"] == 1

    # segments: Asha has come in, Ravi has not; an opted-out customer gets no message and no new code
    assert (await client.patch(f"/api/contacts/{ravi['id']}", json={"opted_out": True})).status_code == 200
    k = next(r for r in data["invites"] if r["phone"] == "447700900111")
    k = next(r for r in (await client.get(f"/api/campaigns/{campaign}/invites")).json()["invites"] if r["code"] == k["code"])
    assert k["opted_out"] and k["message"] is None


async def test_a_customer_can_ask_for_offers_on_their_code_page(client):
    _, post = await live_post("poster")
    mine = (await client.post(f"/api/public/r/{post}/claim", json={"device": "phone-optin-1"})).json()["code"]
    assert (await client.get(f"/api/public/claims/{mine}")).json()["opted_in"] is False
    bad = await client.post(f"/api/public/claims/{mine}/opt-in", json={"phone": "12345678", "agree": True})
    assert bad.status_code == 409
    assert (await client.post(f"/api/public/claims/{mine}/opt-in", json={"phone": "98450 22222", "agree": False})).status_code == 422
    r = await client.post(f"/api/public/claims/{mine}/opt-in", json={"phone": "98450 22222", "name": "Meera", "agree": True})
    assert r.status_code == 200
    assert (await client.get(f"/api/public/claims/{mine}")).json()["opted_in"] is True
    c = next(c for c in (await client.get("/api/businesses/kaapi-kone/contacts")).json()["contacts"] if c["phone"] == "919845022222")
    assert c["source"] == "code_page" and c["name"] == "Meera" and c["codes"] == 1


async def test_contacts_belong_to_their_business(client):
    await client.post("/api/businesses/kaapi-kone/contacts", json={"text": "Zed 98450 33333", "consent": True})
    c = next(c for c in (await client.get("/api/businesses/kaapi-kone/contacts")).json()["contacts"] if c["phone"] == "919845033333")
    client.user["id"] = "00000000-0000-0000-0000-00000000dead"
    assert (await client.get("/api/businesses/kaapi-kone/contacts")).status_code == 404
    assert (await client.delete(f"/api/contacts/{c['id']}")).status_code == 404


async def test_conversion_counts_only_people_who_came_in_from_the_link(client):
    """A post's code typed at the counter (from a caption or poster) is redeemed, but it is not a link conversion."""
    _, post = await live_post("instagram_post")

    def row(data: dict) -> dict:
        return next(p for p in data["posts"] if p["code"] == post)

    await client.post("/api/counter/redeem", json={"code": post, "outside_rules": "test"})  # nobody opened the link
    r = row((await client.get("/api/businesses/kaapi-kone/results")).json())
    assert (r["scans"], r["claims"], r["redeemed"], r["conversion"]) == (0, 0, 1, None)

    await client.post(f"/api/public/r/{post}/visit", json={"device": "phone-conv-1"})
    await client.post(f"/api/public/r/{post}/visit", json={"device": "phone-conv-1"})  # same phone again: one open
    mine = (await client.post(f"/api/public/r/{post}/claim", json={"device": "phone-conv-1"})).json()["code"]
    await client.post("/api/counter/redeem", json={"code": mine, "outside_rules": "test"})
    r = row((await client.get("/api/businesses/kaapi-kone/results")).json())
    assert (r["scans"], r["claims"], r["redeemed"], r["from_link"]) == (1, 1, 2, 1)
    assert r["conversion"] == 1.0  # 1 of 1 who opened came in, never 200%
