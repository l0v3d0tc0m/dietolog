from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import ingest
from conftest import TZ

AUTH = {"Authorization": "Bearer secret"}


@pytest.fixture
def api(conn):
    return TestClient(ingest.create_app(conn, "secret", TZ))


def payload(today, food):
    y = today - timedelta(days=1)
    return {
        "range_from": str(today - timedelta(days=6)), "range_to": str(today),
        "days": [{"date": str(y), "steps": 11000, "active_kcal": 520}],
        "sleep": [{"start": f"{y}T20:30:00Z", "end": f"{today}T04:10:00Z", "deep_min": 85}],
        "food": food,
        "weight": [{"time": f"{y}T05:00:00Z", "kg": 82.4}],
    }


def food(id_, d, kcal=500):
    return {"id": id_, "time": f"{d}T09:00:00Z", "name": "Овсянка", "kcal": kcal}


def test_rejects_bad_token(api, today):
    assert api.post("/ingest", json=payload(today, [])).status_code == 401
    assert api.post("/ingest", json=payload(today, []),
                    headers={"Authorization": "Bearer nope"}).status_code == 401


def test_ingest_stores_everything(api, conn, today):
    r = api.post("/ingest", json=payload(today, [food("a", today)]), headers=AUTH)
    assert r.status_code == 200
    assert conn.execute("SELECT steps FROM daily_activity").fetchone()[0] == 11000
    sleep = conn.execute("SELECT wake_date, duration_min FROM sleep_sessions").fetchone()
    assert sleep[0] == str(today) and sleep[1] == pytest.approx(460)
    assert conn.execute("SELECT weight_kg FROM profile").fetchone()[0] == 82.4


def test_resync_removes_deleted_food_but_keeps_bot_entries(api, conn, toolbox, today):
    api.post("/ingest", json=payload(today, [food("a", today), food("b", today)]), headers=AUTH)
    toolbox.run("log_food", {"name": "Яблоко", "kcal": 80})
    api.post("/ingest", json=payload(today, [food("a", today)]), headers=AUTH)
    ids = {r[0] for r in conn.execute("SELECT id FROM food_entries")}
    assert "a" in ids and "b" not in ids
    assert any(i.startswith("bot-") for i in ids)


def test_resync_is_idempotent(api, conn, today):
    for _ in range(3):
        api.post("/ingest", json=payload(today, [food("a", today)]), headers=AUTH)
    assert conn.execute("SELECT COUNT(*) FROM food_entries").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sleep_sessions").fetchone()[0] == 1


def test_food_outside_range_untouched(api, conn, today):
    old = today - timedelta(days=30)
    api.post("/ingest", json={**payload(today, [food("old", old)]),
                              "range_from": str(old), "range_to": str(old)}, headers=AUTH)
    api.post("/ingest", json=payload(today, []), headers=AUTH)
    assert conn.execute("SELECT COUNT(*) FROM food_entries WHERE id='old'").fetchone()[0] == 1
