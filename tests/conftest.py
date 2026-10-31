"""Shared test setup. Every test gets its own empty data folder, so tests never touch real data."""

import pytest


@pytest.fixture(autouse=True)
def temporary_data_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_APP_DATA_DIR", str(tmp_path))
    return tmp_path
