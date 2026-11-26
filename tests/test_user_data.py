"""P4.1 (B21, C9): user data in Documents/MachineControl/settings, moved there once from the old place."""
import json

import pytest

import PathManager


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    user, old = tmp_path / "user", tmp_path / "v1" / "settings"
    old.mkdir(parents=True)
    monkeypatch.setattr(PathManager, "USER_DIR", user)
    monkeypatch.setattr(PathManager, "legacy_settings_dirs", lambda: [old])
    return user / "settings", old


def test_first_start_copies_the_old_user_files_and_leaves_them(dirs):
    target, old = dirs
    (old / "Default_Settings.json").write_text('{"artisan": {"port": "COM9"}}', encoding="utf-8")
    (old / "stored_positions.json").write_text('[{"name": "a", "x": 1, "y": 2, "z": 3}]', encoding="utf-8")
    (old / "schema.json").write_text("{}", encoding="utf-8")                        # program file: not copied
    report = PathManager.migrate_user_data()
    assert "copied Default_Settings.json" in report and "copied stored_positions.json" in report
    assert json.loads((target / "Default_Settings.json").read_text(encoding="utf-8"))["artisan"]["port"] == "COM9"
    assert not (target / "schema.json").exists() and (old / "stored_positions.json").exists()   # v1.0 keeps its files
    assert PathManager.migrate_user_data() is None                                  # only once
    assert PathManager.get_settings_path("stored_positions.json") == target / "stored_positions.json"


def test_nothing_to_migrate_starts_with_the_templates(dirs):
    target, old = dirs
    assert "nothing found" in PathManager.migrate_user_data()
    path = PathManager.get_settings_path("Default_Settings.json")
    assert path == target / "Default_Settings.json" and path.exists()               # copied from the bundle
    assert PathManager.get_settings_path("schema.json") == PathManager.get_base_dir() / "settings" / "schema.json"


def test_migrate_from_another_folder_keeps_a_backup(dirs, tmp_path):
    target, old = dirs
    PathManager.migrate_user_data()
    PathManager.get_settings_path("custom_sample_holders.json").write_text('{"new": 1}', encoding="utf-8")
    install = tmp_path / "old_install" / "settings"
    install.mkdir(parents=True)
    (install / "custom_sample_holders.json").write_text('{"v1": 1}', encoding="utf-8")
    report = PathManager.migrate_user_data(sources=[install], force=True)
    assert "copied custom_sample_holders.json" in report
    assert json.loads((target / "custom_sample_holders.json").read_text(encoding="utf-8")) == {"v1": 1}
    (backup,) = target.glob("backup_*")
    assert json.loads((backup / "custom_sample_holders.json").read_text(encoding="utf-8")) == {"new": 1}
    assert (target / "MIGRATED.txt").read_text(encoding="utf-8").count("user data moved") == 2
