"""Tools the agent can call. Each one reads or writes the SQLite database."""
import json
import sqlite3
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import db, nutrition

NUM = {"type": "number"}
STR = {"type": "string"}
DATE = {"type": "string", "description": "YYYY-MM-DD; defaults to today"}
MACROS_100 = {
    "kcal_per_100g": NUM, "protein_per_100g": NUM,
    "fat_per_100g": NUM, "carbs_per_100g": NUM,
}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [],
            "additionalProperties": False}


TOOLS = [
    {"name": "get_day_summary",
     "description": "Calories eaten, target, remaining (for today), macros, steps, activity and "
                    "sleep for one day. Use for 'how much can I still eat', 'how was yesterday'.",
     "input_schema": _obj({"date": DATE})},
    {"name": "get_period_summary",
     "description": "Per-day overview of the last N full days (today excluded): eaten vs target, "
                    "energy balance, steps, sleep, weight log, totals.",
     "input_schema": _obj({"days": {"type": "integer", "minimum": 2, "maximum": 60}}, ["days"])},
    {"name": "list_food_entries",
     "description": "All food diary entries for a day (FatSecret entries arrive via Health Connect).",
     "input_schema": _obj({"date": DATE})},
    {"name": "log_food",
     "description": "Add a food diary entry. Only when the user explicitly asks to log food here "
                    "instead of FatSecret, otherwise entries get counted twice.",
     "input_schema": _obj({"name": STR, "kcal": NUM, "protein_g": NUM, "fat_g": NUM,
                           "carbs_g": NUM, "meal": STR,
                           "time": {"type": "string", "description": "ISO time, defaults to now"}},
                          ["name", "kcal"])},
    {"name": "delete_food_entry",
     "description": "Delete a food entry that was logged through this bot (source='bot').",
     "input_schema": _obj({"id": STR}, ["id"])},
    {"name": "get_inventory",
     "description": "Everything in the fridge and pantry, including cooked dishes, with ids.",
     "input_schema": _obj({})},
    {"name": "add_inventory_item",
     "description": "Add a product or cooked dish. For dishes estimate macros per 100 g from the "
                    "ingredients if the user cooked it from inventory items.",
     "input_schema": _obj({"name": STR,
                           "kind": {"type": "string", "enum": ["product", "dish"]},
                           "quantity": NUM,
                           "unit": {"type": "string", "enum": ["g", "ml", "pcs", "portion"]},
                           **MACROS_100,
                           "expires_on": {"type": "string", "description": "YYYY-MM-DD"},
                           "note": STR},
                          ["name", "kind", "quantity", "unit"])},
    {"name": "update_inventory_item",
     "description": "Change an inventory item. 'consume' subtracts an amount (item is removed "
                    "when it reaches zero); other fields overwrite.",
     "input_schema": _obj({"id": {"type": "integer"}, "consume": NUM, "quantity": NUM,
                           "name": STR, "unit": STR, **MACROS_100,
                           "expires_on": STR, "note": STR}, ["id"])},
    {"name": "remove_inventory_item",
     "description": "Remove an item from the inventory completely.",
     "input_schema": _obj({"id": {"type": "integer"}}, ["id"])},
    {"name": "get_preferences",
     "description": "Saved food likes, dislikes, allergies, habits and goals.",
     "input_schema": _obj({})},
    {"name": "add_preference",
     "description": "Remember a food preference, allergy, habit or goal the user mentioned.",
     "input_schema": _obj({"category": {"type": "string",
                                        "enum": ["likes", "dislikes", "allergy", "habit",
                                                 "goal", "other"]},
                           "text": STR}, ["category", "text"])},
    {"name": "remove_preference",
     "description": "Forget a saved preference by id.",
     "input_schema": _obj({"id": {"type": "integer"}}, ["id"])},
    {"name": "get_profile",
     "description": "Body profile and goal settings used for the calorie math.",
     "input_schema": _obj({})},
    {"name": "update_profile",
     "description": "Update body profile or goal. goal_kcal_delta: negative = deficit, "
                    "positive = surplus, 0 = maintenance.",
     "input_schema": _obj({"sex": {"type": "string", "enum": ["m", "f"]},
                           "birth_date": {"type": "string", "description": "YYYY-MM-DD"},
                           "height_cm": NUM, "weight_kg": NUM,
                           "goal_kcal_delta": {"type": "integer"},
                           "protein_g_per_kg": NUM, "fat_g_per_kg": NUM,
                           "active_kcal_factor": NUM})},
    {"name": "log_weight",
     "description": "Record body weight (also updates the profile weight).",
     "input_schema": _obj({"kg": NUM}, ["kg"])},
]

PROFILE_FIELDS = {"sex", "birth_date", "height_cm", "weight_kg", "goal_kcal_delta",
                  "protein_g_per_kg", "fat_g_per_kg", "active_kcal_factor"}
INVENTORY_FIELDS = {"quantity", "name", "unit", "kcal_per_100g", "protein_per_100g",
                    "fat_per_100g", "carbs_per_100g", "expires_on", "note"}


class Toolbox:
    def __init__(self, conn: sqlite3.Connection, tz: ZoneInfo):
        self.conn = conn
        self.tz = tz

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def _date(self, value: str | None) -> date:
        return date.fromisoformat(value) if value else self.today()

    def run(self, name: str, args: dict) -> str:
        handler = getattr(self, f"t_{name}", None)
        if handler is None:
            raise ValueError(f"unknown tool {name}")
        return json.dumps(handler(**args), ensure_ascii=False, default=str)

    # --- diary and summaries ---
    def t_get_day_summary(self, date=None):
        return nutrition.day_summary(self.conn, self._date(date), self.today())

    def t_get_period_summary(self, days):
        return nutrition.period_summary(self.conn, int(days), self.today())

    def t_list_food_entries(self, date=None):
        return db.rows(self.conn, "SELECT * FROM food_entries WHERE date=? ORDER BY time",
                       (self._date(date).isoformat(),))

    def t_log_food(self, name, kcal, protein_g=None, fat_g=None, carbs_g=None, meal=None,
                   time=None):
        ts = datetime.fromisoformat(time) if time else datetime.now(self.tz)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=self.tz)
        entry_id = f"bot-{uuid.uuid4().hex[:8]}"
        with self.conn:
            self.conn.execute(
                """INSERT INTO food_entries (id, source, time, date, name, meal, kcal,
                   protein_g, fat_g, carbs_g) VALUES (?, 'bot', ?,?,?,?,?,?,?,?)""",
                (entry_id, ts.isoformat(), ts.astimezone(self.tz).date().isoformat(), name,
                 meal, kcal, protein_g, fat_g, carbs_g))
        return {"ok": True, "id": entry_id}

    def t_delete_food_entry(self, id):
        with self.conn:
            n = self.conn.execute("DELETE FROM food_entries WHERE id=? AND source='bot'",
                                  (id,)).rowcount
        if not n:
            raise ValueError("no bot entry with that id (FatSecret entries are edited in FatSecret)")
        return {"ok": True}

    # --- inventory ---
    def t_get_inventory(self):
        return db.rows(self.conn, "SELECT * FROM inventory ORDER BY kind, expires_on IS NULL, "
                                  "expires_on, name")

    def t_add_inventory_item(self, **fields):
        bad = set(fields) - INVENTORY_FIELDS - {"kind"}
        if bad:
            raise ValueError(f"unknown fields: {bad}")
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with self.conn:
            cur = self.conn.execute(f"INSERT INTO inventory ({cols}) VALUES ({marks})",
                                    tuple(fields.values()))
        return {"ok": True, "id": cur.lastrowid}

    def t_update_inventory_item(self, id, consume=None, **fields):
        item = db.row(self.conn, "SELECT * FROM inventory WHERE id=?", (id,))
        if not item:
            raise ValueError(f"no inventory item {id}")
        bad = set(fields) - INVENTORY_FIELDS
        if bad:
            raise ValueError(f"unknown fields: {bad}")
        if consume is not None:
            fields["quantity"] = (item["quantity"] or 0) - consume
        with self.conn:
            if "quantity" in fields and fields["quantity"] <= 0:
                self.conn.execute("DELETE FROM inventory WHERE id=?", (id,))
                return {"ok": True, "removed": True}
            if fields:
                sets = ", ".join(f"{k}=?" for k in fields)
                self.conn.execute(f"UPDATE inventory SET {sets} WHERE id=?",
                                  (*fields.values(), id))
        return {"ok": True, "item": db.row(self.conn, "SELECT * FROM inventory WHERE id=?", (id,))}

    def t_remove_inventory_item(self, id):
        with self.conn:
            self.conn.execute("DELETE FROM inventory WHERE id=?", (id,))
        return {"ok": True}

    # --- preferences ---
    def t_get_preferences(self):
        return db.rows(self.conn, "SELECT id, category, text FROM preferences ORDER BY category")

    def t_add_preference(self, category, text):
        with self.conn:
            cur = self.conn.execute("INSERT INTO preferences (category, text) VALUES (?,?)",
                                    (category, text))
        return {"ok": True, "id": cur.lastrowid}

    def t_remove_preference(self, id):
        with self.conn:
            self.conn.execute("DELETE FROM preferences WHERE id=?", (id,))
        return {"ok": True}

    # --- profile ---
    def t_get_profile(self):
        p = nutrition.profile(self.conn)
        p["missing_fields"] = nutrition.missing_profile_fields(p)
        return p

    def t_update_profile(self, **fields):
        bad = set(fields) - PROFILE_FIELDS
        if bad:
            raise ValueError(f"unknown fields: {bad}")
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            with self.conn:
                self.conn.execute(f"UPDATE profile SET {sets} WHERE id=1", tuple(fields.values()))
        return self.t_get_profile()

    def t_log_weight(self, kg):
        now = datetime.now(self.tz)
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO weight_log (time, date, kg) VALUES (?,?,?)",
                              (now.isoformat(), now.date().isoformat(), kg))
            self.conn.execute("UPDATE profile SET weight_kg=? WHERE id=1", (kg,))
        return {"ok": True}
