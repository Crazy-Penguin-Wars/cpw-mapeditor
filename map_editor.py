"""CPW Map Editor launcher.

Keep this file deliberately tiny: application code belongs in cpw_map_editor.
"""

import os
import sys

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)

from src.app import Editor

if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    os.environ["TCL_LIBRARY"] = os.path.join(base, "..", "python-embed", "tcl", "tcl9.0")
    os.environ["TK_LIBRARY"] = os.path.join(base, "..", "python-embed", "tcl", "tk9.0")
    Editor().mainloop()
