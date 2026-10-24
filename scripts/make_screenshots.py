"""Génère les captures de l'interface (docs/screenshots/) avec une IA simulée et une sandbox temporaire.

    uv run python scripts/make_screenshots.py

Aucun appel à une API ni aucun fichier réel n'est touché : tout se passe dans un dossier temporaire.
"""

from __future__ import annotations

import csv
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "screenshots"
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="tribin-demo-"))
    os.environ.update({"TRIBIN_DATA_DIR": str(work / "data"), "TRIBIN_SANDBOX_DIR": str(work / "Agence"),
                       "TRIBIN_DEV_SANDBOX": "1", "TRIBIN_USER": "demo"})
    from fakes import FakeLLM, original_name
    from make_sandbox import make_sandbox
    from PySide6.QtCore import QThreadPool

    import tribin.ui.app as app_mod
    from tribin.config import get_settings
    from tribin.models import LLMAlternative, LLMProposal
    from tribin.service.bin import BinService
    from tribin.service.config_store import AppConfig
    from tribin.ui.onboarding import OnboardingWizard
    from tribin.ui.settings import SettingsDialog
    from tribin.ui.theme import apply_theme

    sandbox = work / "Agence"
    make_sandbox(sandbox)
    with open(sandbox / "expected.csv", encoding="utf-8") as fh:
        expected = {r["file"]: r for r in csv.DictReader(fh)}

    def answer(prompt: str) -> LLMProposal:
        """IA simulée, réaliste : bon dossier, confiance variable, une hésitation de temps en temps."""
        name = original_name(prompt)
        row = expected[name]
        folder = row["expected_folder"]
        confidence = 0.93 if not row["acceptable_folders"] else 0.72
        alternatives = [LLMAlternative(target_folder=a, reasoning="Autre catégorie possible pour ce type de document.")
                        for a in row["acceptable_folders"].split("|") if a][:1]
        if name.lower().startswith(("img_", "scan_")):
            confidence = 0.45
        return LLMProposal(target_folder=folder, description=Path(name).stem.replace("_", " ")[:28],
                           confidence=confidence, alternatives=alternatives,
                           reasoning=f"Le contenu de « {name} » correspond à ce projet et à cette catégorie.")

    app = app_mod.TriBinApplication(["tribin-screenshots"])
    apply_theme(app)
    app_mod.is_being_written = lambda path, delay=2.0: False
    service = BinService(get_settings(), provider_factory=lambda s, m=None: FakeLLM(answer, model="demo"))
    service.update_config(AppConfig(roots=[str(sandbox / "root")], convention_path=str(sandbox / "convention.yaml"),
                                    local_excluded=["**/_PROJET_EN_COURS/**"], onboarding_done=True, privacy_accepted=True))
    controller = app_mod.AppController(app, service, show_ui=False)
    names = ["scan0042.pdf", "Affiche_Noel_final.pdf", "affiche_noel_v2.psd", "IMG_3381.jpg",
             "Planning_site_v2.xlsx", "banniere_web_728x90.png", "devis_signe.pdf", "Document1.docx"]
    controller.drop_paths([sandbox / "inbox" / n for n in names])
    deadline = time.time() + 60
    while time.time() < deadline and len([i for i in service.pending() if i.status == "ready"]) < len(names):
        app.processEvents()
        time.sleep(0.05)

    OUT.mkdir(parents=True, exist_ok=True)

    def save(widget, filename: str, size: tuple[int, int] | None = None) -> None:
        if size:
            widget.resize(*size)
        widget.show()
        app.processEvents()
        widget.grab().save(str(OUT / filename))
        print(f"  {filename}")

    window = controller.bin_window
    controller.refresh_queue()
    by_name = {Path(i.original_path).name: i for i in service.pending()}
    window.select_file(by_name["affiche_noel_v2.psd"].file_id)
    save(window, "corbeille.png", (1240, 780))
    window.select_file(by_name["IMG_3381.jpg"].file_id)
    save(window, "corbeille-a-verifier.png")

    # Simulation d'un lot (les fichiers prêts), puis rangement réel dans la sandbox pour remplir l'Historique.
    from tribin.service.bin import Validation
    from tribin.ui.queue_panel import group_of
    from tribin.ui.simulation_dialog import SimulationDialog

    ready = [i for i in service.pending() if group_of(i) == "ready"]
    prepared = service.prepare([Validation(i.file_id, i.proposal.target_folder, i.proposal.new_name, "accepted")
                                for i in ready])
    save(SimulationDialog(prepared.report), "simulation.png", (860, 640))
    service.commit(prepared)
    controller.refresh_queue()
    window.show_page("history")
    save(window, "historique.png")
    window.show_page("bin")

    widget = controller.drop_widget
    for name, state in (("widget-repos.png", dict(total=0)), ("widget-analyse.png", dict(total=3, analyzing=1)),
                        ("widget-pret.png", dict(total=7, ready=5, check=2))):
        widget.set_state(**state)
        save(widget, name)
    settings_dialog = SettingsDialog(controller)
    save(settings_dialog, "reglages.png", (960, 660))
    settings_dialog.pages.setCurrentIndex(1)
    settings_dialog.nav.button(1).setChecked(True)
    save(settings_dialog, "reglages-ia.png")
    wizard = OnboardingWizard(controller)
    wizard.resize(820, 640)
    save(wizard, "onboarding.png")
    wizard.accept_privacy.setChecked(True)
    for step in range(2, 5):
        wizard.next()
        save(wizard, f"onboarding-{step}.png")
    window.refresh([])
    save(window, "corbeille-vide.png")
    QThreadPool.globalInstance().waitForDone(5000)
    shutil.rmtree(work, ignore_errors=True)
    print(f"Captures écrites dans {OUT}")


if __name__ == "__main__":
    main()
