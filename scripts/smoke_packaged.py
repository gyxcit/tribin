"""Test de fumée de l'application empaquetée (CI) : instance unique + fichier reçu en argument.

    uv run python scripts/smoke_packaged.py <exécutable>

Lance l'application (mode sans écran), lui envoie un fichier par une seconde instance — comme un dépôt sur
le raccourci du bureau (Windows) — puis vérifie que le fichier est dans la corbeille et analysé.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))


def main() -> int:
    exe = Path(sys.argv[1]).resolve()
    work = Path(tempfile.mkdtemp(prefix="tribin-smoke-"))
    env = {**os.environ, "TRIBIN_DATA_DIR": str(work / "data"), "TRIBIN_SANDBOX_DIR": str(work / "sb"),
           "TRIBIN_DEV_SANDBOX": "1", "TRIBIN_USER": "smoke", "QT_QPA_PLATFORM": "offscreen", "ANTHROPIC_API_KEY": ""}
    os.environ.update(env)

    from make_sandbox import make_sandbox

    from tribin.config import get_settings
    from tribin.db import Database
    from tribin.service.config_store import AppConfig, save_config
    from tribin.service.queue import QueueStore

    make_sandbox(work / "sb")
    db = Database(get_settings().db_path)
    save_config(db, AppConfig(roots=[str(work / "sb" / "root")], convention_path=str(work / "sb" / "convention.yaml"),
                              onboarding_done=True, privacy_accepted=True))

    plist = exe.parents[1] / "Info.plist" if exe.parent.name == "MacOS" else None
    if plist:
        types = plistlib.loads(plist.read_bytes()).get("CFBundleDocumentTypes", [])
        assert any("public.item" in t.get("LSItemContentTypes", []) for t in types), "CFBundleDocumentTypes absent"
        print("Info.plist : CFBundleDocumentTypes OK")

    first = subprocess.Popen([str(exe)], env=env)
    try:
        time.sleep(10)
        assert first.poll() is None, f"l'application s'est arrêtée (code {first.returncode})"
        target = work / "sb" / "inbox" / "scan0042.pdf"
        second = subprocess.run([str(exe), str(target)], env=env, timeout=60)
        assert second.returncode == 0, f"seconde instance : code {second.returncode}"
        store = QueueStore(db)
        deadline = time.time() + 60
        while time.time() < deadline:
            items = store.active()
            if items and items[0].status == "ready":
                break
            time.sleep(1)
        items = store.active()
        assert items and items[0].name == "scan0042.pdf" and items[0].status == "ready", items
        assert not target.exists() and Path(items[0].staged_path).exists()
        print(f"OK : fichier reçu par l'instance en cours, déposé et analysé ({items[0].status}).")
        return 0
    finally:
        first.kill()


if __name__ == "__main__":
    sys.exit(main())
