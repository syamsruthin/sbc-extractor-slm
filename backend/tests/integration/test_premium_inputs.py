"""Rating areas and household premium quotes (v2.1 T2.1, T2.2) and the request profile (T2.3)."""

import pytest

from sbcx.infra.db import session_scope
from sbcx.infra.models import PremiumRow
from sbcx.services.catalog import age_band, counted_members
from tests.fixtures import f1, seed_f1

MODA = "17933TX0010006-00"


def seed_premiums():
    rows = []
    for area, base in (("Rating Area 3", 500.0), ("Rating Area 10", 450.0)):
        for band, mult in (("0-14", 0.6), ("16", 0.65), ("38", 0.98), ("40", 1.0), ("64 and over", 3.0)):
            rows.append(
                PremiumRow(
                    plan_key=MODA[:14], state="TX", rating_area=area, age=band, monthly_premium=base * mult
                )
            )
    rows.append(
        PremiumRow(
            plan_key="99999TX0000001", state="TX", rating_area="Rating Area 2", age="40", monthly_premium=1
        )
    )
    with session_scope() as s:
        s.add_all(rows)


@pytest.mark.parametrize(
    "age,band",
    [(0, "0-14"), (14, "0-14"), (15, "15"), (40, "40"), (63, "63"), (64, "64 and over"), (90, "64 and over")],
)
def test_age_band(age, band):
    assert age_band(age) == band


def test_only_the_three_oldest_children_count():
    assert counted_members([40, 38, 16, 12, 10, 8]) == [True, True, True, True, True, False]
    assert counted_members([40, 20, 19, 18, 17]) == [True, True, True, True, False]
    assert counted_members([22, 21, 70]) == [True, True, True]


def test_rating_areas_are_sorted_by_number(client):
    seed_premiums()
    r = client.get("/api/v1/catalog/rating-areas", params={"state": "tx"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "TX"
    assert [i["rating_area"] for i in body["items"]] == ["Rating Area 2", "Rating Area 3", "Rating Area 10"]
    assert body["items"][1]["plans_priced"] == 1
    assert client.get("/api/v1/catalog/rating-areas", params={"state": "WY"}).json()["items"] == []


def test_household_quote(client):
    seed_f1()
    seed_premiums()
    url = f"/api/v1/catalog/plans/{MODA}/premium-quote"
    r = client.get(url, params={"rating_area": "Rating Area 3", "ages": "40,38,12,10,8,5"})
    assert r.status_code == 200, r.text
    q = r.json()
    assert [m["counted"] for m in q["members"]] == [True, True, True, True, True, False]
    assert q["monthly_total"] == pytest.approx(500 + 490 + 3 * 300) and q["missing_ages"] == []
    # a member whose band has no rate: no total
    q = client.get(url, params={"rating_area": "Rating Area 3", "ages": "40,30"}).json()
    assert q["monthly_total"] is None and q["missing_ages"] == [30]
    # plan not sold in that rating area
    q = client.get(url, params={"rating_area": "Rating Area 2", "ages": "40"}).json()
    assert q["monthly_total"] is None and q["missing_ages"] == [40]


@pytest.mark.parametrize("ages", ["", "abc", "40,200", ",".join(["30"] * 11), "-1"])
def test_household_quote_rejects_bad_ages(client, ages):
    seed_f1()
    r = client.get(
        f"/api/v1/catalog/plans/{MODA}/premium-quote", params={"rating_area": "Rating Area 3", "ages": ages}
    )
    assert r.status_code == 422, r.text


def test_household_quote_unknown_plan(client):
    r = client.get(
        "/api/v1/catalog/plans/nope/premium-quote", params={"rating_area": "Rating Area 3", "ages": "40"}
    )
    assert r.status_code == 404


def test_profile_round_trips_and_is_validated(client):
    seed_f1()
    profile = {"ages": [40, 38], "rating_areas": {"TX": "Rating Area 3", "MO": "Rating Area 1"}}
    body = {**f1()["request"], "explain": False, "profile": profile}
    r = client.post("/api/v1/comparisons", json=body)
    assert r.status_code == 201, r.text
    got = client.get(f"/api/v1/comparisons/{r.json()['id']}").json()
    assert got["request"]["profile"] == profile
    # the profile doesn't change the result
    plain = client.post("/api/v1/comparisons", json={**f1()["request"], "explain": False}).json()
    assert plain["result"]["result_hash"] == r.json()["result"]["result_hash"]
    bad = client.post("/api/v1/comparisons", json={**body, "profile": {"ages": [130]}})
    assert bad.status_code == 422
    bad = client.post("/api/v1/comparisons", json={**body, "reference_price_overrides": {"imaging": -5}})
    assert bad.status_code == 422
