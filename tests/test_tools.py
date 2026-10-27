import json

import pytest


def run(tb, name, args=None):
    return json.loads(tb.run(name, args or {}))


def test_inventory_consume_and_auto_remove(toolbox):
    item = run(toolbox, "add_inventory_item",
               {"name": "Курица", "kind": "product", "quantity": 1000, "unit": "g"})
    left = run(toolbox, "update_inventory_item", {"id": item["id"], "consume": 300})
    assert left["item"]["quantity"] == 700
    gone = run(toolbox, "update_inventory_item", {"id": item["id"], "consume": 700})
    assert gone["removed"]
    assert run(toolbox, "get_inventory") == []


@pytest.mark.parametrize("tool,args", [
    ("add_inventory_item", {"name": "x", "kind": "product", "quantity": 1, "unit": "g",
                            "name) VALUES (1); DROP TABLE inventory; --": 1}),
    ("update_inventory_item", {"id": 1, "id = 1; DROP TABLE inventory; --": 1}),
    ("update_profile", {"weight_kg = 1; --": 1}),
])
def test_unknown_fields_rejected(toolbox, tool, args):
    run(toolbox, "add_inventory_item", {"name": "a", "kind": "product", "quantity": 1, "unit": "g"})
    with pytest.raises((ValueError, TypeError)):
        toolbox.run(tool, args)
    assert toolbox.conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 1


def test_only_bot_food_can_be_deleted(toolbox, conn, today):
    conn.execute("INSERT INTO food_entries (id, source, time, date, kcal) "
                 "VALUES ('hc1', 'health_connect', ?, ?, 100)", (f"{today}T10:00", str(today)))
    with pytest.raises(ValueError):
        toolbox.run("delete_food_entry", {"id": "hc1"})
    entry = run(toolbox, "log_food", {"name": "Яблоко", "kcal": 80})
    assert run(toolbox, "delete_food_entry", {"id": entry["id"]})["ok"]


def test_log_food_lands_on_today(toolbox, today):
    run(toolbox, "log_food", {"name": "Яблоко", "kcal": 80})
    assert [e["name"] for e in run(toolbox, "list_food_entries")] == ["Яблоко"]


def test_preferences_roundtrip(toolbox):
    p = run(toolbox, "add_preference", {"category": "allergy", "text": "орехи"})
    assert run(toolbox, "get_preferences")[0]["text"] == "орехи"
    run(toolbox, "remove_preference", {"id": p["id"]})
    assert run(toolbox, "get_preferences") == []


def test_profile_reports_missing_fields(toolbox):
    assert set(run(toolbox, "get_profile")["missing_fields"]) == {"sex", "birth_date", "height_cm",
                                                                    "weight_kg"}
    run(toolbox, "log_weight", {"kg": 81.5})
    assert run(toolbox, "get_profile")["weight_kg"] == 81.5


def test_every_declared_tool_has_handler(toolbox):
    from app.tools import TOOLS
    for t in TOOLS:
        assert hasattr(toolbox, f"t_{t['name']}"), t["name"]
