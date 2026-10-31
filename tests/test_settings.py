import pytest

from engine.storage import database
from engine.storage.settings import SETTINGS, SettingError, SettingsStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    database.initialize(db)
    return SettingsStore(db)


def test_defaults_before_anything_is_saved(store):
    assert store.get_all() == {key: spec.default for key, spec in SETTINGS.items()}


def test_saved_value_is_read_back(store):
    store.set("display_timezone", "America/New_York")
    assert store.get("display_timezone") == "America/New_York"


def test_saved_value_survives_a_new_store_on_the_same_file(store):
    store.set("glow_strength", 80)
    assert SettingsStore(store.db_path).get("glow_strength") == 80


@pytest.mark.parametrize(
    "key, bad_value",
    [
        ("display_timezone", "Mars/Olympus"),
        ("display_timezone", 5),
        ("glow_strength", 101),
        ("glow_strength", -1),
        ("glow_strength", True),
        ("glow_strength", "50"),
        ("reduce_motion", "yes"),
    ],
)
def test_bad_values_are_refused_with_a_reason(store, key, bad_value):
    with pytest.raises(SettingError) as problem:
        store.set(key, bad_value)
    assert str(problem.value)  # a plain English reason is always given
    assert store.get(key) == SETTINGS[key].default  # nothing was saved


def test_unknown_setting_is_refused(store):
    with pytest.raises(SettingError, match="no setting called"):
        store.set("not_a_setting", 1)
