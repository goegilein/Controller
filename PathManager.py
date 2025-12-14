"""
Path manager for resolving file paths in both development and executable environments.
This handles both running from source and running from a PyInstaller executable.
"""

import sys
from pathlib import Path


def get_base_dir():
    """
    Get the base directory of the application.
    Works in both development (running from source) and executable (PyInstaller).
    """
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable
        # PyInstaller extracts bundled files to _internal directory
        base_dir = Path(sys._MEIPASS)
    else:
        # Running from source
        base_dir = Path(__file__).resolve().parent
    
    return base_dir


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


def get_settings_path(filename="Default_Settings.json"):
    """Get path to a settings file."""
    base_dir = get_base_dir()
    settings_dir = base_dir / "settings"
    return settings_dir / filename


def get_library_path(library_name):
    """Get path to a library folder."""
    base_dir = get_base_dir()
    libraries_dir = base_dir / "libraries"
    return libraries_dir / library_name


# Convenient module-level getters
BASE_DIR = get_base_dir()
GUI_DIR = BASE_DIR / "GUI_files"
SETTINGS_DIR = BASE_DIR / "settings"
LIBRARIES_DIR = BASE_DIR / "libraries"
DRIVERS_DIR = BASE_DIR / "Drivers"
