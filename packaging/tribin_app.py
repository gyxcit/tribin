"""Point d'entrée de l'application empaquetée (PyInstaller)."""

import sys

from tribin.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
