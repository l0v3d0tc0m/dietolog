import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import db
from app.tools import Toolbox

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
TZ = ZoneInfo("Europe/Moscow")


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "test.db")


@pytest.fixture
def toolbox(conn):
    return Toolbox(conn, TZ)


@pytest.fixture
def today():
    return datetime.now(TZ).date()


@pytest.fixture
def profile(toolbox):
    # 30 y.o. male, 180 cm, 80 kg -> BMR = 800 + 1125 - 150 + 5 = 1780
    toolbox.run("update_profile", {"sex": "m", "birth_date": "1990-01-01", "height_cm": 180,
                                   "weight_kg": 80, "goal_kcal_delta": -400})
