import sys
import shutil
from pathlib import Path


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


def get_settings_path(filename="Default_Settings.json", ensure_exists=True):
    """
    Get path to a settings file.
    Looks for the file in the external settings folder next to the executable (in frozen mode)
    or in the project root directory (in development mode).
    
    If ensure_exists is True and the settings file does not exist externally,
    it copies the bundled template from the internal package directory (if available)
    or creates the directory so the application always has a valid file to read and write.
    """
    app_dir = get_app_dir()
    settings_dir = app_dir / "settings"
    target_file = settings_dir / filename

    if target_file.exists():
        return target_file

    # If running from source and file is in cwd settings instead
    if not getattr(sys, 'frozen', False):
        cwd_settings = Path.cwd() / "settings"
        if (cwd_settings / filename).exists():
            return cwd_settings / filename

    if ensure_exists and not target_file.exists():
        settings_dir.mkdir(parents=True, exist_ok=True)
        # Check if a bundled copy exists in the internal package directory
        bundle_file = get_base_dir() / "settings" / filename
        if bundle_file.exists():
            try:
                shutil.copy2(bundle_file, target_file)
            except Exception:
                # If cannot write externally (e.g. read-only filesystem), fallback to bundled
                return bundle_file

    return target_file


def get_library_path(library_name):
    """Get path to a library folder."""
    base_dir = get_base_dir()
    libraries_dir = base_dir / "libraries"
    return libraries_dir / library_name


# Convenient module-level getters
BASE_DIR = get_base_dir()
APP_DIR = get_app_dir()
GUI_DIR = BASE_DIR / "GUI_files"
SETTINGS_DIR = APP_DIR / "settings"
LIBRARIES_DIR = BASE_DIR / "libraries"
DRIVERS_DIR = BASE_DIR / "Drivers"

