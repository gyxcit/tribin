"""Premier lancement, en quatre étapes courtes (section 6.8), listées dans une colonne à gauche.

1. Bienvenue et confidentialité · 2. Vos dossiers (la convention est déduite automatiquement)
3. Votre activité (facultatif) · 4. Intelligence artificielle (fournisseur et clé, facultatifs)
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
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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
from tribin.ui.components import ChoiceCard, divider, muted, section
from tribin.ui.folder_picker import excluded_picker, roots_picker
from tribin.ui.icons import logo_pixmap

if TYPE_CHECKING:
    from tribin.ui.app import AppController

ROW_CHARS = 62  # passage à la ligne des choix, selon la longueur des libellés
STEPS = ("Bienvenue", "Vos dossiers", "Votre activité", "Intelligence artificielle")
RAIL_NOTES = ("Rien n'est supprimé ni écrasé. Chaque rangement s'annule depuis l'Historique.",
              "Rien n'est supprimé ni écrasé. Chaque rangement s'annule depuis l'Historique.",
              "Vos réponses restent sur cet ordinateur.",
              "Seul un extrait des fichiers est envoyé à l'IA, jamais le fichier entier.")
# (clé, nom, description, où créer la clé, recommandé)
PROVIDERS = (("mistral", "Mistral AI", "Hébergée en Europe. L'IA par défaut de TriBin, testée sur des dossiers d'agence.",
              "console.mistral.ai", True),
             ("anthropic", "Claude (Anthropic)", "Les modèles Claude d'Anthropic.", "console.anthropic.com", False),
             ("gemini", "Gemini (Google)", "Les modèles Gemini de Google, avec une offre gratuite limitée.",
              "aistudio.google.com", False))


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
        row, used = None, ROW_CHARS
        for choice in choices:
            if used + len(choice) > ROW_CHARS:
                if row is not None:
                    row.addStretch()
                row, used = QHBoxLayout(), 0
                row.setSpacing(6)
                rows.addLayout(row)
            used += len(choice) + 4
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


class StepRail(QFrame):
    """Colonne de gauche : logo, étapes numérotées (faites, en cours, à venir) et une note rassurante."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(220)
        col = QVBoxLayout(self)
        col.setContentsMargins(20, 24, 20, 20)
        col.setSpacing(0)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(26))
        name = QLabel("TriBin")
        name.setObjectName("Brand")
        brand.addWidget(logo)
        brand.addWidget(name)
        brand.addStretch()
        col.addLayout(brand)
        col.addSpacing(28)
        self.steps: list[tuple[QLabel, QLabel]] = []
        for index, text in enumerate(STEPS):
            row = QHBoxLayout()
            row.setSpacing(12)
            number = QLabel(str(index + 1))
            number.setObjectName("StepNum")
            number.setFixedSize(24, 24)
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label = QLabel(text)
            label.setObjectName("StepText")
            label.setWordWrap(True)
            row.addWidget(number, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label, 1)
            col.addLayout(row)
            col.addSpacing(16)
            self.steps.append((number, label))
        col.addStretch()
        self.note = QLabel()
        self.note.setObjectName("RailNote")
        self.note.setWordWrap(True)
        col.addWidget(self.note)

    def set_current(self, current: int) -> None:
        for index, (number, label) in enumerate(self.steps):
            state = "done" if index < current else "current" if index == current else "todo"
            number.setText("✓" if state == "done" else str(index + 1))
            for widget in (number, label):
                widget.setProperty("state", state)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        self.note.setText(RAIL_NOTES[max(0, min(current, len(RAIL_NOTES) - 1))])


class CheckedPage(QWizardPage):
    """Page dont le bouton « Continuer » vérifie d'abord une condition (message clair sinon)."""

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


def page_layout(page: QWizardPage, title: str, lead: str) -> QVBoxLayout:
    """Titre et phrase d'introduction en haut de la page, alignés à gauche."""
    layout = QVBoxLayout(page)
    layout.setContentsMargins(36, 32, 36, 12)
    layout.setSpacing(0)
    heading = QLabel(title)
    heading.setObjectName("Title")
    heading.setWordWrap(True)
    layout.addWidget(heading)
    layout.addSpacing(6)
    layout.addWidget(muted(lead))
    layout.addSpacing(22)
    return layout


def field_block(layout: QVBoxLayout, title: str, help_text: str = "") -> None:
    layout.addWidget(section(title))
    if help_text:
        layout.addSpacing(2)
        layout.addWidget(muted(help_text))
    layout.addSpacing(10)


class OnboardingWizard(QWizard):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.setWindowTitle("Bienvenue dans TriBin")
        self.resize(820, 640)
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setButtonLayout([QWizard.WizardButton.CancelButton, QWizard.WizardButton.Stretch,
                              QWizard.WizardButton.BackButton, QWizard.WizardButton.NextButton,
                              QWizard.WizardButton.FinishButton])
        for button, text in [(QWizard.WizardButton.NextButton, "Continuer"), (QWizard.WizardButton.BackButton, "Retour"),
                             (QWizard.WizardButton.FinishButton, "Terminer"), (QWizard.WizardButton.CancelButton, "Annuler")]:
            self.setButtonText(button, text)
        for key, name in ((QWizard.WizardButton.NextButton, "Primary"), (QWizard.WizardButton.FinishButton, "Primary"),
                          (QWizard.WizardButton.CancelButton, "Ghost")):
            button = self.button(key)
            button.setObjectName(name)
            button.style().unpolish(button)  # bouton déjà créé par Qt : recalculer son style
            button.style().polish(button)
        self.rail = StepRail()
        self.setSideWidget(self.rail)
        self.addPage(self._welcome_page())
        self.addPage(self._folder_page())
        self.addPage(self._about_page())
        self.addPage(self._ai_page())
        self.currentIdChanged.connect(lambda _: self.rail.set_current(self.pageIds().index(self.currentId())
                                                                         if self.currentId() >= 0 else 0))
        self.rail.set_current(0)

    # --- 1. bienvenue -----------------------------------------------------------------------------

    def _welcome_page(self) -> QWizardPage:
        page = QWizardPage()
        layout = page_layout(page, "Bienvenue dans TriBin",
                             "Glissez un fichier sur TriBin : l'IA propose où le ranger et comment le renommer, "
                             "selon les habitudes de votre équipe. Vous validez d'un clic, ou vous corrigez.")
        for title, text in (("Rien n'est perdu", "Aucun fichier n'est supprimé ni écrasé, et chaque rangement "
                                                 "s'annule depuis l'Historique."),
                            ("Vous gardez la main", "Plusieurs fichiers à la fois ? Une simulation montre tout "
                                                    "avant le moindre déplacement."),
                            ("TriBin apprend", "Vos corrections lui apprennent vos habitudes, fichier après fichier.")):
            layout.addWidget(section(title))
            layout.addSpacing(2)
            layout.addWidget(muted(text))
            layout.addSpacing(14)
        layout.addWidget(divider())
        layout.addSpacing(14)
        layout.addWidget(muted(PRIVACY_NOTICE))
        layout.addSpacing(10)
        self.accept_privacy = QCheckBox("J'ai compris")
        page.registerField("privacy*", self.accept_privacy)
        layout.addWidget(self.accept_privacy)
        layout.addStretch()
        return page

    # --- 2. vos dossiers --------------------------------------------------------------------------

    def _folder_page(self) -> QWizardPage:
        page = CheckedPage(lambda: None if self._roots() else "Choisissez au moins un dossier à ranger.")
        layout = page_layout(page, "Quels dossiers TriBin doit-il ranger ?",
                             "Choisissez le dossier de l'équipe, sur cet ordinateur, le NAS ou Dropbox. "
                             "TriBin y apprend votre façon de ranger.")
        field_block(layout, "Dossiers à ranger", "Les fichiers ne seront rangés que dans ces dossiers.")
        self.roots = roots_picker(self.c.service.config.roots)
        layout.addWidget(self.roots)
        layout.addSpacing(18)
        layout.addWidget(divider())
        layout.addSpacing(18)
        field_block(layout, "Dossiers à ne jamais toucher (facultatif)",
                    "Par exemple un projet InDesign en cours : le déplacer casserait ses liens.")
        self.excluded = excluded_picker(self.c.service.config.local_excluded, self._roots)
        layout.addWidget(self.excluded)
        layout.addSpacing(18)
        layout.addWidget(divider())
        layout.addSpacing(14)
        layout.addWidget(muted("La façon de ranger (convention) est déduite de ces dossiers. "
                               "S'ils sont vides, TriBin part d'une convention type d'agence."))
        self.use_existing = QPushButton("J'ai déjà un fichier de convention")
        self.use_existing.setObjectName("Link")
        self.use_existing.setCheckable(True)
        layout.addWidget(self.use_existing, 0, Qt.AlignmentFlag.AlignLeft)
        self.file_box = QWidget()
        file_row = QHBoxLayout(self.file_box)
        file_row.setContentsMargins(0, 4, 0, 0)
        self.conv_path = QLineEdit(self.c.service.config.convention_path)
        self.conv_path.setPlaceholderText("Fichier de convention (.yaml)")
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.conv_path, 1)
        file_row.addWidget(browse)
        layout.addWidget(self.file_box)
        self.file_box.setVisible(False)
        self.use_existing.toggled.connect(self.file_box.setVisible)
        layout.addStretch()
        return page

    # --- 3. votre activité ------------------------------------------------------------------------

    def _about_page(self) -> QWizardPage:
        page = QWizardPage()
        layout = page_layout(page, "Quelques questions sur votre activité",
                             "Facultatif : cela aide l'IA à comprendre votre contexte. Vous pouvez passer cette étape.")
        self.chips: dict[str, ChipGroup] = {}
        for key, label, choices, multiple in QUESTIONS:
            layout.addWidget(section(label + (" (plusieurs choix possibles)" if multiple else "")))
            layout.addSpacing(6)
            self.chips[key] = ChipGroup(choices, multiple)
            layout.addWidget(self.chips[key])
            layout.addSpacing(10)
        self.context = QLineEdit()
        self.context.setPlaceholderText("Autre chose à préciser ? Ex. : agence de 20 personnes, clients agroalimentaires")
        layout.addWidget(self.context)
        layout.addStretch()
        return page

    # --- 4. intelligence artificielle ---------------------------------------------------------------

    def _ai_page(self) -> QWizardPage:
        page = QWizardPage()
        layout = page_layout(page, "Quelle IA utiliser ?",
                             "Elle propose le dossier et le nom de chaque fichier. Vous pourrez en changer "
                             "dans les réglages.")
        self.provider_group = QButtonGroup(page)
        self.provider_cards: dict[str, ChoiceCard] = {}
        for key, name, description, _, recommended in PROVIDERS:
            card = ChoiceCard(name, description, "Recommandé" if recommended else "")
            card.radio.setProperty("provider", key)
            card.radio.toggled.connect(lambda checked: checked and self._provider_changed())
            self.provider_group.addButton(card.radio)
            self.provider_cards[key] = card
            layout.addWidget(card)
            layout.addSpacing(8)
        layout.addSpacing(10)
        self.key_title = section("")
        layout.addWidget(self.key_title)
        layout.addSpacing(2)
        self.key_hint = muted()
        layout.addWidget(self.key_hint)
        layout.addSpacing(10)
        key_row = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_key = QPushButton("Afficher")
        self.show_key.setObjectName("Link")
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(lambda on: (
            self.api_key.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password),
            self.show_key.setText("Masquer" if on else "Afficher")))
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(self.show_key)
        layout.addLayout(key_row)
        layout.addStretch()
        current = self.c.service.config.provider or self.c.service.settings.provider
        self.set_provider(current if current in self.provider_cards else "mistral")
        return page

    def provider(self) -> str:
        checked = self.provider_group.checkedButton()
        return checked.property("provider") if checked else "mistral"

    def set_provider(self, key: str) -> None:
        self.provider_cards[key].radio.setChecked(True)

    def _provider_changed(self) -> None:
        key = self.provider()
        _, name, _, console, _ = next(p for p in PROVIDERS if p[0] == key)
        has_key = bool(self.c.service.settings.for_provider(key).api_key)
        self.key_title.setText(f"Clé API {name.split(' (')[0]}")
        self.api_key.setPlaceholderText("Une clé est déjà enregistrée sur cet ordinateur" if has_key
                                        else "Collez votre clé ici")
        self.key_hint.setText(("Une clé est déjà enregistrée : rien à faire. " if has_key else
                               f"Créez-la sur {console}, puis collez-la ici. Sans clé, TriBin fonctionne mais "
                               "chaque fichier est à ranger à la main. ")
                              + "Elle est rangée dans le trousseau de l'ordinateur.")

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
            QMessageBox.warning(self, "TriBin", "Choisissez au moins un dossier à ranger.")
            return
        provider = self.provider()
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
        if self.use_existing.isChecked():
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
            return target, ("Convention déduite de vos dossiers. Vous pouvez la relire et l'ajuster à tout moment "
                            f"(Réglages › Dossiers) : {target}")
        shutil.copy2(Path(resources.__file__).with_name("convention.example.yaml"), target)
        return target, ("Vos dossiers sont vides : TriBin part d'une convention type d'agence "
                        "(client / année / projet / catégorie), modifiable dans les réglages.")
