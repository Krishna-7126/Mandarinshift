"""
LocalShift Command-Line Interface entry point for PyInstaller application bundle.
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(errors="backslashreplace")
    except Exception:
        pass

from localshift.cli import main

if __name__ == "__main__":
    main()

