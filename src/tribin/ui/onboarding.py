"""Onboarding du premier lancement : confidentialité, 5 questions, racines, convention (section 6.8)."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from tribin.config import save_api_key
from tribin import resources
from tribin.convention.loader import Convention, save_convention
from tribin.llm.base import LLMError
from tribin.mapping.infer import infer_convention, propose_structure, structure_to_convention
from tribin.mapping.scanner import scan_root
from tribin.service.profile import PRIVACY_NOTICE, QUESTIONS, build_profile, save_profile
from tribin.ui.settings import path_list

if TYPE_CHECKING:
    from tribin.ui.app import AppController


class OnboardingWizard(QWizard):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.setWindowTitle("Bienvenue dans TriBin")
        self.resize(720, 560)
        for button, text in [(QWizard.WizardButton.NextButton, "Suivant >"), (QWizard.WizardButton.BackButton, "< Précédent"),
                             (QWizard.WizardButton.FinishButton, "Terminer"), (QWizard.WizardButton.CancelButton, "Annuler")]:
            self.setButtonText(button, text)

        welcome = QWizardPage()
        welcome.setTitle("Bienvenue")
        wl = QVBoxLayout(welcome)
        intro = QLabel("TriBin fonctionne comme la Corbeille : tu y glisses un fichier, l'IA propose où le ranger "
                       "et comment le renommer selon la convention de ton équipe. Tu valides ou tu corriges ; "
                       "rien n'est jamais supprimé ni écrasé, et tout est annulable.")
        intro.setWordWrap(True)
        privacy = QLabel(PRIVACY_NOTICE)
        privacy.setWordWrap(True)
        self.accept_privacy = QCheckBox("J'ai compris")
        welcome.registerField("privacy*", self.accept_privacy)
        for w in (intro, privacy, self.accept_privacy):
            wl.addWidget(w)
        wl.addStretch()
        self.addPage(welcome)

        questions = QWizardPage()
        questions.setTitle("Quelques questions (toutes facultatives)")
        ql = QFormLayout(questions)
        self.combos: dict[str, QComboBox] = {}
        self.checks: dict[str, list[QCheckBox]] = {}
        for key, label, choices, multiple in QUESTIONS:
            if multiple:
                box = QWidget()
                row = QHBoxLayout(box)
                row.setContentsMargins(0, 0, 0, 0)
                self.checks[key] = [QCheckBox(choice) for choice in choices]
                for cb in self.checks[key]:
                    row.addWidget(cb)
                ql.addRow(label, box)
            else:
                combo = QComboBox()
                combo.addItems(["—", *choices])
                self.combos[key] = combo
                ql.addRow(label, combo)
        self.context = QPlainTextEdit()
        self.context.setPlaceholderText("Précise ton contexte en quelques mots")
        self.context.setMaximumHeight(90)
        ql.addRow("Contexte", self.context)
        self.addPage(questions)

        roots_page = QWizardPage()
        roots_page.setTitle("Répertoires de référence et zones exclues")
        rl = QVBoxLayout(roots_page)
        rl.addWidget(QLabel("Racines : dossiers (disque local ou NAS) dans lesquels TriBin range les fichiers."))
        box, self.roots = path_list(controller.service.config.roots)
        rl.addWidget(box)
        rl.addWidget(QLabel("Zones exclues : TriBin n'y touchera jamais (un motif par ligne)."))
        self.excluded = QPlainTextEdit("**/_PROJET_EN_COURS/**")
        self.excluded.setMaximumHeight(80)
        rl.addWidget(self.excluded)
        self.addPage(roots_page)

        conv_page = QWizardPage()
        conv_page.setTitle("Convention de rangement")
        cl = QVBoxLayout(conv_page)
        self.mode = QButtonGroup(conv_page)
        options = [("existing", "J'ai déjà un fichier de convention (ex. sur le NAS)"),
                   ("map", "Cartographier l'existant et en déduire une convention"),
                   ("scratch", "Créer une structure de zéro avec l'IA"),
                   ("example", "Partir de la convention d'exemple")]
        for i, (key, label) in enumerate(options):
            radio = QRadioButton(label)
            radio.setProperty("mode", key)
            self.mode.addButton(radio, i)
            cl.addWidget(radio)
        self.mode.button(1).setChecked(True)
        file_row = QHBoxLayout()
        self.conv_path = QLineEdit(controller.service.config.convention_path)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.conv_path)
        file_row.addWidget(browse)
        cl.addLayout(file_row)
        cl.addWidget(QLabel(f"Clé API {controller.service.settings.provider.capitalize()} "
                            "(facultatif, modifiable dans les réglages) :"))
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        cl.addWidget(self.api_key)
        cl.addStretch()
        self.addPage(conv_page)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Fichier de convention", "", "YAML (*.yaml *.yml)")
        if path:
            self.conv_path.setText(path)
            self.mode.button(0).setChecked(True)

    def answers(self) -> dict[str, object]:
        result: dict[str, object] = {k: c.currentText() for k, c in self.combos.items() if c.currentIndex() > 0}
        for key, boxes in self.checks.items():
            picked = [b.text() for b in boxes if b.isChecked()]
            if picked:
                result[key] = picked
        if self.context.toPlainText().strip():
            result["contexte"] = self.context.toPlainText().strip()
        return result

    def accept(self) -> None:
        svc = self.c.service
        roots = [self.roots.item(i).text() for i in range(self.roots.count())]
        if not roots:
            QMessageBox.warning(self, "TriBin", "Ajoute au moins un répertoire de référence.")
            return
        key = self.api_key.text().strip()
        if key:
            try:
                save_api_key(key, svc.settings.provider)
            except Exception:
                pass
            svc.settings = replace(svc.settings, api_key=key)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            llm = self.c.llm_or_none()
            save_profile(svc.settings.profile_path, build_profile(self.answers(), llm))
            convention_path = self._make_convention(roots, llm)
        except (LLMError, OSError, ValueError) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "TriBin", f"Étape impossible : {exc}")
            return
        QApplication.restoreOverrideCursor()
        cfg = svc.config
        cfg.roots = roots
        cfg.local_excluded = [line.strip() for line in self.excluded.toPlainText().splitlines() if line.strip()]
        cfg.convention_path = str(convention_path)
        cfg.onboarding_done = True
        cfg.privacy_accepted = True
        svc.update_config(cfg)
        super().accept()

    def _make_convention(self, roots: list[str], llm) -> Path:
        mode = self.mode.checkedButton().property("mode")
        target = self.c.service.settings.data_dir / "convention.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "existing":
            path = Path(self.conv_path.text().strip())
            if not path.is_file():
                raise ValueError("fichier de convention introuvable")
            return path
        if target.exists():
            target = target.with_name(f"convention_{len(list(target.parent.glob('convention*.yaml'))) + 1}.yaml")
        if mode == "example":
            shutil.copy2(Path(resources.__file__).with_name("convention.example.yaml"), target)
        elif mode == "map":
            profiles = [p for r in roots for p in scan_root(Path(r), Convention())]
            save_convention(infer_convention(profiles), target)
            QMessageBox.information(self, "TriBin", f"Convention déduite de l'existant : {target}\n"
                                    "Relis-la (structure, catégories, clients) et corrige-la si besoin.")
        else:
            if llm is None:
                raise ValueError("une clé API est nécessaire pour créer une structure avec l'IA")
            save_convention(structure_to_convention(propose_structure(svc_profile(self.c), llm)), target)
        return target


def svc_profile(controller: AppController) -> str:
    try:
        return controller.service.settings.profile_path.read_text(encoding="utf-8")
    except OSError:
        return ""
