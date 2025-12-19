"""
Build script to compile main_Controller.py into an executable with automatic versioning.
Usage: python build_executable.py [--bump-patch | --bump-minor | --bump-major]
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime


class VersionManager:
    """Manage version numbers for the executable."""
    
    def __init__(self, version_file="version.json"):
        self.version_file = Path(version_file)
        self.version_data = self._load_version()
    
    def _load_version(self):
        """Load version from file or create default."""
        if self.version_file.exists():
            try:
                with open(self.version_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading version file: {e}")
                return {"major": 1, "minor": 0, "patch": 0}
        else:
            return {"major": 1, "minor": 0, "patch": 0}
    
    def _save_version(self):
        """Save version to file."""
        with open(self.version_file, 'w') as f:
            json.dump(self.version_data, f, indent=2)
    
    def get_version_string(self):
        """Get version as string (e.g., '1.0.0')."""
        return f"{self.version_data['major']}.{self.version_data['minor']}.{self.version_data['patch']}"
    
    def bump_patch(self):
        """Increment patch version (1.0.0 -> 1.0.1)."""
        self.version_data['patch'] += 1
        self._save_version()
        return self.get_version_string()
    
    def bump_minor(self):
        """Increment minor version and reset patch (1.0.5 -> 1.1.0)."""
        self.version_data['minor'] += 1
        self.version_data['patch'] = 0
        self._save_version()
        return self.get_version_string()
    
    def bump_major(self):
        """Increment major version and reset minor/patch (1.5.3 -> 2.0.0)."""
        self.version_data['major'] += 1
        self.version_data['minor'] = 0
        self.version_data['patch'] = 0
        self._save_version()
        return self.get_version_string()


class ExecutableBuilder:
    """Build executable using PyInstaller."""
    
    def __init__(self, main_file="main_Controller.py", output_name="Controller"):
        self.main_file = main_file
        self.output_name = output_name
        self.dist_dir = Path("dist")
        self.build_dir = Path("build")
        self.version_manager = VersionManager()
    
    def check_dependencies(self):
        """Check if PyInstaller is installed."""
        try:
            import PyInstaller
            print(f"✓ PyInstaller found: {PyInstaller.__version__}")
            return True
        except ImportError:
            print("✗ PyInstaller not found!")
            print("Install it with: pip install pyinstaller")
            return False
    
    def clean_build_dirs(self):
        """Clean previous build artifacts."""
        print("Cleaning previous builds...")
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        if self.dist_dir.exists():
            shutil.rmtree(self.dist_dir)
        print("✓ Clean complete")
    
    def build(self, version=None):
        """Build the executable."""
        if not self.check_dependencies():
            return False
        
        if version is None:
            version = self.version_manager.get_version_string()
        
        exe_name = f"{self.output_name}_{version}"
        
        print(f"\n{'='*60}")
        print(f"Building {exe_name}.exe")
        print(f"{'='*60}\n")
        
        self.clean_build_dirs()
        
        # PyInstaller command
        cmd = [
            "pyinstaller",
            "--onefile",                    # Single executable file
            "--windowed",                   # No console window
            "--name", exe_name,             # Output name
            "--icon=GUI_files/resources/crosshair.png",  # Icon (optional)
            "--add-data", "GUI_files;GUI_files",  # Include GUI files
            "--add-data", "settings;settings",    # Include settings
            "--add-data", "libraries;libraries",  # Include libraries
            "--add-data", "Drivers;Drivers",      # Include drivers
            "--collect-all", "PyQt6",             # Include PyQt6
            self.main_file
        ]
        
        try:
            print(f"Running: {' '.join(cmd)}\n")
            result = subprocess.run(cmd, check=True)
            
            if result.returncode == 0:
                exe_path = self.dist_dir / f"{exe_name}.exe"
                if exe_path.exists():
                    print(f"\n✓ Build successful!")
                    print(f"✓ Executable: {exe_path}")
                    print(f"✓ Size: {exe_path.stat().st_size / (1024*1024):.2f} MB")
                    return True
        except subprocess.CalledProcessError as e:
            print(f"\n✗ Build failed with error code {e.returncode}")
            return False
        except Exception as e:
            print(f"\n✗ Error during build: {e}")
            return False
        
        return False
    
    def build_with_version_bump(self, bump_type="patch"):
        """Build and automatically bump version."""
        if bump_type == "major":
            new_version = self.version_manager.bump_major()
        elif bump_type == "minor":
            new_version = self.version_manager.bump_minor()
        else:  # patch (default)
            new_version = self.version_manager.bump_patch()
        
        print(f"Version bumped to: {new_version}")
        return self.build(version=new_version)


def main():
    """Main entry point."""
    builder = ExecutableBuilder()
    
    # Check for version bump arguments
    bump_type = None
    if len(sys.argv) > 1:
        if sys.argv[1] == "--bump-patch":
            bump_type = "patch"
        elif sys.argv[1] == "--bump-minor":
            bump_type = "minor"
        elif sys.argv[1] == "--bump-major":
            bump_type = "major"
        elif sys.argv[1] in ["-h", "--help"]:
            print(__doc__)
            sys.exit(0)
    
    # Build
    if bump_type:
        success = builder.build_with_version_bump(bump_type)
    else:
        success = builder.build()
    
    if success:
        print(f"\n{'='*60}")
        print("Build completed successfully!")
        print(f"{'='*60}")
        sys.exit(0)
    else:
        print(f"\n{'='*60}")
        print("Build failed!")
        print(f"{'='*60}")
        sys.exit(1)


if __name__ == "__main__":
    main()
