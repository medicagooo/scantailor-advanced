"""Interactive entry point; explicitly add sibling modules for embedded Python."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scantailor_menu.ui import main
if __name__ == "__main__":
    raise SystemExit(main())
