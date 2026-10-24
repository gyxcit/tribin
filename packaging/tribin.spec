# -*- mode: python ; coding: utf-8 -*-
# Empaquetage minimal, sans signature (phase 4) :
#   uv sync --extra packaging
#   uv run python scripts/make_icons.py
#   uv run pyinstaller packaging/tribin.spec --noconfirm
# Résultat : dist/TriBin/TriBin.exe (Windows) ou dist/TriBin.app (macOS).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

HERE = Path(SPECPATH)
SRC = HERE.parent / "src"

datas = collect_data_files("tribin") + collect_data_files("docx") + collect_data_files("pptx")
binaries = []
hiddenimports = collect_submodules("tribin")
# Fournisseurs Gemini et Mistral : obligatoires (un .exe sans eux afficherait « module absent »).
hiddenimports += collect_submodules("google.genai") + collect_submodules("mistralai")
# Trousseau du système (clé API) : backends chargés dynamiquement, à embarquer explicitement.
hiddenimports += collect_submodules("keyring")
datas += copy_metadata("keyring")
if sys.platform == "win32":
    hiddenimports += collect_submodules("win32ctypes")
for package in ("pypdfium2", "pypdfium2_raw", "psd_tools"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(HERE / "tribin_app.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore"],
    noarchive=False,
)
if sys.platform == "win32":
    # OpenSSL : toujours celui de Python. Sinon PyInstaller peut prendre une autre version trouvée dans le PATH
    # (celle de Git, par ex.) et « import ssl » échoue dans l'exe : plus aucun fournisseur d'IA ne se connecte.
    python_dlls = Path(sys.base_prefix) / "DLLs"
    own = [(dll.name, str(dll), "BINARY") for dll in python_dlls.glob("lib*-3*.dll")
           if dll.name.lower().startswith(("libssl", "libcrypto"))]
    replaced = {name.lower() for name, _, _ in own}
    a.binaries = [b for b in a.binaries if b[0].lower() not in replaced] + own

pyz = PYZ(a.pure)
icon = str(HERE / ("tribin.icns" if sys.platform == "darwin" else "tribin.ico"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TriBin", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="TriBin")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="TriBin.app",
        icon=icon,
        bundle_identifier="fr.tribin.app",
        info_plist={
            "CFBundleName": "TriBin",
            "CFBundleDisplayName": "TriBin",
            "NSHighResolutionCapable": True,
            # Permet de déposer n'importe quel fichier sur l'icône du Dock (QFileOpenEvent).
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Tous les fichiers",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["public.item", "public.data", "public.content"],
                }
            ],
        },
    )
