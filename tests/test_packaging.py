"""The installed Windows app (packaging/) finds its files and starts its engine correctly."""

import sys

from desktop import launcher
from engine import paths


def test_from_source_files_come_from_the_project_folder():
    root = paths.resource_dir()
    assert (root / "ui" / "index.html").exists()
    assert (paths.config_dir() / "markets.json").exists()
    assert (paths.examples_dir() / "tjr_bootcamp_strategy.py").exists()
    assert launcher.engine_command(8765)[1:3] == ["-m", "engine"]


def test_installed_app_reads_files_from_its_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.is_packaged()
    assert paths.ui_dir() == tmp_path / "ui"
    assert paths.config_dir() == tmp_path / "config"
    assert paths.examples_dir() == tmp_path / "scripts" / "examples"


def test_installed_app_starts_its_engine_with_its_own_exe(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\TradingApp\TradingApp.exe")
    assert launcher.engine_command(8765) == [r"C:\Apps\TradingApp\TradingApp.exe", "--engine", "--port", "8765"]


def test_data_folder_is_not_inside_the_app(monkeypatch, tmp_path):
    """Updating or uninstalling the app must never touch the owner's data."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert tmp_path / "bundle" not in paths.data_dir().parents
