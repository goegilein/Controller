import os
import sys
import shutil
from pathlib import Path

# everything the app writes for the user: logs, runs, profiles, settings (REVISION_PLAN.md C9, P4.1);
# MACHINECONTROL_USER_DIR overrides it (tests)
USER_DIR = Path(os.environ.get("MACHINECONTROL_USER_DIR", Path.home() / "Documents" / "MachineControl"))


def get_base_dir():
    """
    Get the internal base directory (bundled assets).
    In frozen mode (PyInstaller), this points to sys._MEIPASS where assets are extracted.
    In development mode, this points to the source root directory.
    """
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent
    
    return base_dir


def get_app_dir():
    """
    Get the external application directory where the executable / project resides.
    In frozen mode, this is the folder containing the .exe file.
    In development mode, this is the folder containing the project root.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_gui_file_path(filename):
    """Get path to a GUI .ui file."""
    base_dir = get_base_dir()
    gui_dir = base_dir / "GUI_files"
    return gui_dir / filename


def get_resource_path(filename):
    """Get path to a resource file (images, etc.)."""
    base_dir = get_base_dir()
    resource_dir = base_dir / "GUI_files" / "resources"
    return resource_dir / filename


# user data (B21, C9, REVISION_PLAN.md P4.1): these files belong to the user and live in USER_DIR / "settings";
# everything else in settings/ (schema.json) is part of the program and is read from the bundle
USER_FILES = ("Default_Settings.json", "stored_positions.json", "stored_points.json", "custom_sample_holders.json")
MIGRATION_NOTE = "MIGRATED.txt"


def user_settings_dir():
    return USER_DIR / "settings"


def legacy_settings_dirs():
    """Where v1.0 / 2.0 before P4.1 kept the user files: next to the program (and the working folder from source)."""
    dirs = [get_app_dir() / "settings"]
    if not getattr(sys, "frozen", False):
        dirs.append(Path.cwd() / "settings")
    unique = []
    for d in dirs:
        if d.resolve() not in [u.resolve() for u in unique]:
            unique.append(d)
    return unique


def migrate_user_data(sources=None, force=False):
    """One-time copy of the user files from the old place into USER_DIR / "settings" (C9).

    Runs once: the note file MIGRATED.txt records what was copied from where. The old files are not changed or
    deleted, so v1.0 keeps working with them. `force` (start with --migrate-from <folder>) copies again: the
    files already in the user folder are moved to a backup folder first. Returns a text for the user, or None if
    nothing was done."""
    from datetime import datetime
    target = user_settings_dir()
    note = target / MIGRATION_NOTE
    if note.exists() and not force:
        return None
    sources = [Path(s) for s in (sources or legacy_settings_dirs())]
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target.mkdir(parents=True, exist_ok=True)
    if force:
        backup = target / f"backup_{datetime.now():%Y%m%d_%H%M%S}"
        for name in USER_FILES:
            if (target / name).exists():
                backup.mkdir(exist_ok=True)
                shutil.move(str(target / name), str(backup / name))
    copied = []
    for name in USER_FILES:
        if (target / name).exists():
            continue
        source = next((d / name for d in sources if (d / name).is_file()), None)
        if source is not None:
            tmp = target / (name + ".tmp")
            shutil.copy2(source, tmp)
            os.replace(tmp, target / name)
            copied.append(f"{name} from {source.parent}")
    lines = [f"{stamp}: user data moved to {target} (REVISION_PLAN.md P4.1)."]
    lines += [f"  copied {c}" for c in copied] or [
        f"  nothing found in {', '.join(str(d) for d in sources)} – started with the default settings.",
        "  If Machine Control 1.x is installed in another folder, close this app and start it once with",
        '  --migrate-from "<1.x folder>\\settings" to take over its settings, stored positions and sample holders.']
    lines.append("  The old files were not changed; Machine Control 1.0 still uses them.")
    with open(note, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return "\n".join(lines)


def get_settings_path(filename="Default_Settings.json", ensure_exists=True):
    """Path of a settings file.

    User files (USER_FILES) are in USER_DIR / "settings": the first call moves them there from the old place
    (migrate_user_data); a missing one is created from the bundled template if ensure_exists. Other files
    (schema.json) are read from the program's own settings folder.
    """
    if filename not in USER_FILES:
        return get_base_dir() / "settings" / filename
    try:
        migrate_user_data()
    except OSError:
        pass                                   # read-only user folder: the template below is used
    target = user_settings_dir() / filename
    if ensure_exists and not target.exists():
        bundle_file = get_base_dir() / "settings" / filename
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if bundle_file.exists():
                shutil.copy2(bundle_file, target)
        except OSError:
            return bundle_file
    return target


def get_library_path(library_name):
    """Get path to a library folder."""
    base_dir = get_base_dir()
    libraries_dir = base_dir / "libraries"
    return libraries_dir / library_name


# Convenient module-level getters
BASE_DIR = get_base_dir()
APP_DIR = get_app_dir()
GUI_DIR = BASE_DIR / "GUI_files"
SETTINGS_DIR = USER_DIR / "settings"            # user settings (P4.1)
LIBRARIES_DIR = BASE_DIR / "libraries"
DRIVERS_DIR = BASE_DIR / "Drivers"

