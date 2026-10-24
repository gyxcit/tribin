"""Onboarding du premier lancement, en quatre écrans courts (section 6.8).

1. Bienvenue et confidentialité · 2. Ton dossier (la convention est déduite automatiquement)
3. Toi, en quelques clics (facultatif) · 4. Ton IA (fournisseur et clé, facultatifs)
"""

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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from tribin import resources
from tribin.config import save_api_key
from tribin.convention.loader import Convention, save_convention
from tribin.llm.base import LLMError
from tribin.mapping.infer import infer_convention
from tribin.mapping.scanner import scan_root
from tribin.service.profile import PRIVACY_NOTICE, QUESTIONS, build_profile, save_profile
from tribin.ui.components import section
from tribin.ui.folder_picker import excluded_picker, roots_picker
from tribin.ui.icons import logo_pixmap
from tribin.ui.settings import PROVIDER_LABELS

if TYPE_CHECKING:
    from tribin.ui.app import AppController

CHIPS_PER_ROW = 4


class ChipGroup(QWidget):
    """Choix en boutons à cliquer (un seul, ou plusieurs) : plus simple qu'une liste déroulante."""

    def __init__(self, choices: list[str], multiple: bool):
        super().__init__()
        rows = QVBoxLayout(self)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(False)
        self.multiple = multiple
        row = None
        for index, choice in enumerate(choices):
            if index % CHIPS_PER_ROW == 0:
                if row is not None:
                    row.addStretch()
                row = QHBoxLayout()
                row.setSpacing(6)
                rows.addLayout(row)
            button = QPushButton(choice)
            button.setObjectName("Chip")
            button.setCheckable(True)
            self.group.addButton(button)
            row.addWidget(button)
        if row is not None:
            row.addStretch()
        self.group.buttonToggled.connect(self._toggled)

    def _toggled(self, button: QPushButton, checked: bool) -> None:
        if checked and not self.multiple:  # un seul choix, mais on peut tout décocher (facultatif)
            for other in self.group.buttons():
                if other is not button:
                    other.setChecked(False)

    def value(self) -> object:
        picked = [b.text() for b in self.group.buttons() if b.isChecked()]
        return picked if self.multiple else (picked[0] if picked else None)


class CheckedPage(QWizardPage):
    """Page dont le bouton « Suivant » vérifie d'abord une condition (message clair sinon)."""

    def __init__(self, check=None):
        super().__init__()
        self._check = check

    def validatePage(self) -> bool:  # noqa: N802 — API Qt
        if self._check is None:
            return True
        message = self._check()
        if message:
            QMessageBox.information(self, "TriBin", message)
            return False
        return True


class OnboardingWizard(QWizard):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.setWindowTitle("Bienvenue dans TriBin")
        self.resize(760, 600)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setPixmap(QWizard.WizardPixmap.LogoPixmap, logo_pixmap(56))
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        for button, text in [(QWizard.WizardButton.NextButton, "Suivant"), (QWizard.WizardButton.BackButton, "Retour"),
                             (QWizard.WizardButton.FinishButton, "C'est parti"), (QWizard.WizardButton.CancelButton, "Annuler")]:
            self.setButtonText(button, text)
        for primary in (QWizard.WizardButton.NextButton, QWizard.WizardButton.FinishButton):
            button = self.button(primary)
            button.setObjectName("Primary")
            button.style().unpolish(button)  # bouton déjà créé par Qt : recalculer son style
            button.style().polish(button)
        self.addPage(self._welcome_page())
        self.addPage(self._folder_page())
        self.addPage(self._about_page())
        self.addPage(self._ai_page())

    # --- 1. bienvenue -----------------------------------------------------------------------------

    def _welcome_page(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Bienvenue dans TriBin")
        page.setSubTitle("Étape 1 sur 4 · Le tri de tes fichiers, sans effort.")
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        for text in ("Tu glisses un fichier sur TriBin. L'IA te propose où le ranger et comment le renommer, "
                     "selon les habitudes de ton équipe.",
                     "Tu valides d'un clic, ou tu corriges. Rien n'est jamais supprimé ni écrasé, et tout s'annule."):
            label = QLabel(text)
            label.setWordWrap(True)
            layout.addWidget(label)
        privacy = QLabel(PRIVACY_NOTICE)
        privacy.setObjectName("Muted")
        privacy.setWordWrap(True)
        layout.addSpacing(8)
        layout.addWidget(privacy)
        self.accept_privacy = QCheckBox("J'ai compris")
        page.registerField("privacy*", self.accept_privacy)
        layout.addWidget(self.accept_privacy)
        layout.addStretch()
        return page

    # --- 2. ton dossier ---------------------------------------------------------------------------

    def _folder_page(self) -> QWizardPage:
        page = CheckedPage(lambda: None if self._roots() else "Choisis au moins un dossier à ranger.")
        page.setTitle("Quel dossier ranger ?")
        page.setSubTitle("Étape 2 sur 4 · Le dossier de l'équipe : sur ton ordinateur, sur le NAS ou dans Dropbox.")
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(section("Dossiers à ranger"))
        self.roots = roots_picker(self.c.service.config.roots)
        layout.addWidget(self.roots)

        layout.addSpacing(6)
        layout.addWidget(section("Dossiers à ne jamais toucher (facultatif)"))
        self.excluded = excluded_picker(self.c.service.config.local_excluded, self._roots)
        self.excluded.setToolTip("Par exemple un projet InDesign en cours : le déplacer casserait ses liens.")
        layout.addWidget(self.excluded)

        layout.addSpacing(6)
        layout.addWidget(section("Convention de rangement"))
        self.mode = QButtonGroup(page)
        auto = QRadioButton("Déduire automatiquement de ce dossier (recommandé)")
        auto.setProperty("mode", "map")
        existing = QRadioButton("J'ai déjà un fichier de convention (par exemple sur le NAS)")
        existing.setProperty("mode", "existing")
        for index, radio in enumerate((auto, existing)):
            self.mode.addButton(radio, index)
            layout.addWidget(radio)
        auto.setChecked(True)
        file_row = QHBoxLayout()
        self.conv_path = QLineEdit(self.c.service.config.convention_path)
        self.conv_path.setPlaceholderText("Fichier de convention (.yaml)")
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.conv_path)
        file_row.addWidget(browse)
        self.file_box = QWidget()
        self.file_box.setLayout(file_row)
        file_row.setContentsMargins(24, 0, 0, 0)
        layout.addWidget(self.file_box)
        hint = QLabel("TriBin repère la structure et le nommage déjà en place. Si le dossier est vide, "
                      "il part d'une convention type d'agence (client / année / projet / catégorie).")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.mode.buttonToggled.connect(lambda *_: self.file_box.setVisible(existing.isChecked()))
        self.file_box.setVisible(False)
        layout.addStretch()
        return page

    # --- 3. toi ----------------------------------------------------------------------------------

    def _about_page(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Quelques mots sur toi")
        page.setSubTitle("Étape 3 sur 4 · Facultatif : ça aide l'IA à comprendre ton contexte. Tu peux passer.")
        layout = QVBoxLayout(page)
        layout.setSpacing(6)
        self.chips: dict[str, ChipGroup] = {}
        for key, label, choices, multiple in QUESTIONS:
            caption = QLabel(label + (" (plusieurs choix possibles)" if multiple else ""))
            caption.setStyleSheet("font-weight: 600;")
            layout.addWidget(caption)
            self.chips[key] = ChipGroup(choices, multiple)
            layout.addWidget(self.chips[key])
            layout.addSpacing(6)
        self.context = QLineEdit()
        self.context.setPlaceholderText("Autre chose à préciser ? Ex. : agence de 20 personnes, clients agroalimentaires")
        layout.addWidget(self.context)
        layout.addStretch()
        return page

    # --- 4. ton IA -------------------------------------------------------------------------------

    def _ai_page(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Ton IA")
        page.setSubTitle("Étape 4 sur 4 · Le service qui propose les rangements. Modifiable plus tard dans les Réglages.")
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(section("Fournisseur"))
        self.provider = QComboBox()
        for key, label in PROVIDER_LABELS.items():
            self.provider.addItem(label, key)
        current = self.c.service.config.provider or self.c.service.settings.provider
        self.provider.setCurrentIndex(max(0, self.provider.findData(current)))
        self.provider.currentIndexChanged.connect(lambda _: self._provider_changed())
        layout.addWidget(self.provider)
        layout.addWidget(section("Clé API (facultatif)"))
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.api_key)
        self.key_hint = QLabel()
        self.key_hint.setObjectName("Muted")
        self.key_hint.setWordWrap(True)
        layout.addWidget(self.key_hint)
        layout.addStretch()
        self._provider_changed()
        return page

    def _provider_changed(self) -> None:
        provider = self.provider.currentData()
        label = PROVIDER_LABELS[provider]
        has_key = bool(self.c.service.settings.for_provider(provider).api_key)
        self.api_key.setPlaceholderText("Une clé est déjà configurée sur cet ordinateur" if has_key
                                        else f"Colle ta clé API {label}")
        self.key_hint.setText(("Rien à faire : la clé déjà configurée sera utilisée. " if has_key else
                               "Sans clé, TriBin fonctionne mais chaque fichier sera à ranger à la main. ")
                              + "La clé est rangée dans le trousseau du système, jamais dans un fichier partagé.")

    # --- valeurs et fin ---------------------------------------------------------------------------

    def _roots(self) -> list[str]:
        return self.roots.values()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Fichier de convention", "", "YAML (*.yaml *.yml)")
        if path:
            self.conv_path.setText(path)

    def answers(self) -> dict[str, object]:
        result = {key: group.value() for key, group in self.chips.items() if group.value()}
        if self.context.text().strip():
            result["contexte"] = self.context.text().strip()
        return result

    def accept(self) -> None:
        svc = self.c.service
        roots = self._roots()
        if not roots:
            QMessageBox.warning(self, "TriBin", "Choisis au moins un dossier à ranger.")
            return
        provider = self.provider.currentData()
        cfg = svc.config
        cfg.provider, cfg.model = provider, ""  # modèle par défaut du fournisseur
        svc.update_config(cfg)
        svc.settings = svc.settings.for_provider(provider)
        key = self.api_key.text().strip()
        if key:
            try:
                save_api_key(key, provider)
            except Exception:  # trousseau indisponible : la clé reste valable pour cette session
                pass
            svc.settings = replace(svc.settings, api_key=key)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            save_profile(svc.settings.profile_path, build_profile(self.answers(), self.c.llm_or_none()))
            convention_path, note = self._make_convention(roots)
        except (LLMError, OSError, ValueError) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "TriBin", f"Étape impossible : {exc}")
            return
        QApplication.restoreOverrideCursor()
        cfg = svc.config
        cfg.roots = roots
        cfg.local_excluded = self.excluded.values()
        cfg.convention_path = str(convention_path)
        cfg.onboarding_done = True
        cfg.privacy_accepted = True
        svc.update_config(cfg)
        if note:
            QMessageBox.information(self, "TriBin", note)
        super().accept()

    def _make_convention(self, roots: list[str]) -> tuple[Path, str]:
        """Convention : fichier existant, sinon déduite des dossiers, sinon convention type."""
        if self.mode.checkedButton().property("mode") == "existing":
            path = Path(self.conv_path.text().strip())
            if not path.is_file():
                raise ValueError("fichier de convention introuvable")
            return path, ""
        target = self.c.service.settings.data_dir / "convention.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(f"convention_{len(list(target.parent.glob('convention*.yaml'))) + 1}.yaml")
        profiles = [p for r in roots for p in scan_root(Path(r), Convention())]
        if any(p.file_count for p in profiles):
            save_convention(infer_convention(profiles), target)
            return target, ("Convention déduite de tes dossiers. Tu peux la relire et l'ajuster à tout moment "
                            f"(Réglages > Général) : {target}")
        shutil.copy2(Path(resources.__file__).with_name("convention.example.yaml"), target)
        return target, ("Ton dossier est vide : TriBin part d'une convention type d'agence "
                        "(client / année / projet / catégorie), modifiable dans les Réglages.")
