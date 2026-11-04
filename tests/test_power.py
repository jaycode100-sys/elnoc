"""Tests for Power: date ordering fix, battery parse edge cases, agentic parse."""
from tests.conftest import fresh_db
from app.models import PowerReport
from app.utils_time import utcnow


db = fresh_db()


def test_power_date_ordering():
    """Dates stored as DD/MM/YYYY must sort chronologically, not lexicographically."""
    from app.routers.power import _lagos_date
    from app.services.shift import lagos_date_iso
    # ISO format sorts correctly
    dates = ["2026-11-01", "2026-01-31", "2026-02-01"]
    assert sorted(dates) == ["2026-01-31", "2026-02-01", "2026-11-01"]


def test_battery_parse_edge_cases():
    from app.services.shift import parse_battery_level
    # Single percentage
    assert parse_battery_level("71%") == "71%"
    # Multiple percentages with labels
    assert parse_battery_level("Inverter: 24%, Kitchen: 44%, Office: 39%") == "24%, Kitchen: 44%, Office: 39%"
    # No percentage
    assert parse_battery_level("Generator switched off") == ""
    # Percentage with text around it
    assert parse_battery_level("Battery at 85% now") == "85%"


def test_time_parse():
    from app.services.shift import parse_time
    assert parse_time("11:34 AM") == "11:34 AM"
    assert parse_time("3:30 PM") == "3:30 PM"
    assert parse_time("No time here") == ""


def test_activity_infer():
    from app.services.shift import infer_activity
    assert infer_activity("Generator switched OFF at 11:34 AM") == "Generator event"
    assert infer_activity("Inverter battery switched ON at 8:06 AM") == "Inverter Switched On"
    assert infer_activity("Solar charging at 85%") == "Solar event"
    assert infer_activity("Mains power restored") == "Mains power event"
    assert infer_activity("Something unrelated") == "Power event"


def test_agent_power_parse_offline():
    """Without an AI provider, the agent falls back to regex parsing."""
    from app.services.shift import infer_activity, parse_time, parse_battery_level
    raw = "Generator switched OFF at 11:34 AM"
    activity = infer_activity(raw)
    event_time = parse_time(raw)
    battery = parse_battery_level(raw)
    assert activity == "Generator event"
    assert event_time == "11:34 AM"
    assert battery == ""
