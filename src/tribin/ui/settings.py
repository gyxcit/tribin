"""Réglages, rangés par catégories dans une colonne à gauche : Dossiers, Intelligence artificielle,
Apprentissage, Système. Chaque réglage : titre et aide à gauche, contrôle à droite."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tribin.config import save_api_key
from tribin.learning.corrections import team_rule_alerts
from tribin.learning.rules_store import delete_rule, list_rules, update_rule
from tribin.service.bin import AUTO_MIN_CONFIDENCE
from tribin.convention.loader import PERSONAL_DEPTH
from tribin.service.conventions import (
    create_convention,
    current_mode,
    has_date_prefix,
    set_date_prefix,
    set_personal_depth,
)
from tribin.service.profile import PRIVACY_NOTICE, save_profile
from tribin.ui import system_integration
from tribin.ui.components import (
    ApiKeyField,
    ChoiceCard,
    ThresholdSlider,
    ToggleSwitch,
    divider,
    muted,
    section,
)
from tribin.ui.folder_picker import excluded_picker, roots_picker
from tribin.ui.hotkey import HOTKEY_LABEL
from tribin.ui.icons import line_icon
from tribin.ui.theme import mono_font
from tribin.ui.onboarding import MODE_CHOICES, PROVIDERS

if TYPE_CHECKING:
    from tribin.ui.app import AppController

DEPTH_EXAMPLE = ["Etudes", "Certifications", "Universite", "Licence", "2026"]
MODELS = {"anthropic": ["claude-haiku-5-5", "claude-sonnet-5-5"],
          "gemini": ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest"],
          "mistral": ["mistral-medium-latest", "mistral-small-latest", "mistral-large-latest"]}
PAGES = (("folders", "Dossiers", "folder"), ("filing", "Rangement", "files"),
         ("ai", "Intelligence artificielle", "sparkle"),
         ("learning", "Apprentissage", "brain"), ("system", "Système", "monitor"))


class SettingsPage(QScrollArea):
    """Page de réglages : titre, phrase d'introduction, puis une ligne par réglage."""

    def __init__(self, title: str, lead: str):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(32, 28, 32, 24)
        self.body.setSpacing(0)
        heading = QLabel(title)
        heading.setObjectName("Title")
        self.body.addWidget(heading)
        self.body.addSpacing(4)
        self.body.addWidget(muted(lead))
        self.body.addSpacing(20)
        self.setWidget(content)

    def add_row(self, title: str, help_text: str, control: QWidget) -> None:
        self.body.addWidget(divider())
        row = QHBoxLayout()
        row.setContentsMargins(0, 18, 0, 18)
        row.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(4)
        heading = section(title)
        heading.setWordWrap(True)
        left.addWidget(heading)
        if help_text:
            left.addWidget(muted(help_text))
        left.addStretch()
        holder = QWidget()
        holder.setFixedWidth(180)
        holder.setLayout(left)
        row.addWidget(holder, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(control, 1, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(row)

    def finish(self) -> None:
        self.body.addStretch()


def column(*widgets: QWidget, spacing: int = 8) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        if isinstance(widget, QWidget):
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft if isinstance(widget, QPushButton) else Qt.AlignmentFlag(0))
        else:
            layout.addLayout(widget)
    return box


class SettingsDialog(QDialog):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.setWindowTitle("TriBin — Réglages")
        self.resize(960, 660)

        self.pages = QStackedWidget()
        for build in (self._folders_page, self._filing_page, self._ai_page, self._learning_page, self._system_page):
            page = build()
            page.finish()
            self.pages.addWidget(page)

        nav = QFrame()
        nav.setObjectName("Sidebar")
        nav.setFixedWidth(220)
        nav_col = QVBoxLayout(nav)
        nav_col.setContentsMargins(12, 20, 12, 12)
        nav_col.setSpacing(2)
        title = QLabel("Réglages")
        title.setObjectName("Brand")
        title.setContentsMargins(10, 0, 0, 14)
        nav_col.addWidget(title)
        self.nav = QButtonGroup(self)
        for index, (_, label, icon) in enumerate(PAGES):
            button = QPushButton(label)
            button.setObjectName("NavItem")
            button.setIcon(line_icon(icon))
            button.setIconSize(QSize(18, 18))
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, i=index: self.pages.setCurrentIndex(i))
            self.nav.addButton(button, index)
            nav_col.addWidget(button)
        self.nav.button(0).setChecked(True)
        nav_col.addStretch()

        foot = QFrame()
        foot.setObjectName("PaneFoot")
        buttons = QHBoxLayout(foot)
        buttons.setContentsMargins(36, 12, 24, 12)
        buttons.addStretch()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Enregistrer")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self.pages, 1)
        right.addWidget(foot)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(nav)
        outer.addLayout(right, 1)

    # --- pages --------------------------------------------------------------------------------

    def _folders_page(self) -> SettingsPage:
        cfg = self.c.service.config
        page = SettingsPage("Dossiers", "Le mode d'utilisation et les dossiers que TriBin peut ranger.")
        self.initial_mode = current_mode(self.c.service)
        self.mode_group = QButtonGroup(self)
        self.mode_cards: dict[str, ChoiceCard] = {}
        cards = []
        for key, title, description in MODE_CHOICES:
            card = ChoiceCard(title, description)
            card.radio.setProperty("mode", key)
            self.mode_group.addButton(card.radio)
            self.mode_cards[key] = card
            cards.append(card)
        self.mode_cards[self.initial_mode].radio.setChecked(True)
        page.add_row("Utilisation", "Changer de mode crée la convention correspondante ; rien n'est déplacé.",
                     column(*cards))
        self.roots = roots_picker(cfg.roots)
        page.add_row("Dossiers à ranger", "TriBin ne range que dans ces dossiers.", self.roots)
        self.excluded = excluded_picker(cfg.local_excluded, self.roots.values)
        page.add_row("Dossiers à ne jamais toucher", "Rien n'y est déplacé ni renommé.", self.excluded)
        return page

    def _filing_page(self) -> SettingsPage:
        """Comment ranger : convention, profondeur des dossiers (mode personnel) et rangement automatique."""
        cfg = self.c.service.config
        page = SettingsPage("Rangement", "La façon de ranger, la profondeur des dossiers et le rangement automatique.")
        conv_row = QHBoxLayout()
        self.convention = QLineEdit(cfg.convention_path)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse_convention)
        conv_row.addWidget(self.convention, 1)
        conv_row.addWidget(browse)
        remap = QPushButton("Réanalyser les dossiers")
        remap.setToolTip("Relit la structure des dossiers à ranger (après une réorganisation, par exemple).")
        remap.clicked.connect(self.c.remap)
        page.add_row("Convention de rangement", "Vos catégories et la façon de nommer les fichiers."
                     if self.initial_mode == "personal" else "Fichier partagé par l'équipe, sur cet ordinateur ou le NAS.",
                     column(conv_row, remap))
        page.add_row("Nom des fichiers", "TriBin renomme chaque fichier rangé selon la convention.",
                     self._naming_box())
        self.depth_buttons = QButtonGroup(self)
        self.initial_depth = self._current_depth()
        if self.initial_mode == "personal":
            page.add_row("Profondeur des dossiers", "Combien de niveaux l'IA peut utiliser dans une catégorie : "
                         "elle range à la racine de la catégorie ou dans un sous-dossier, selon le fichier.",
                         self._depth_box())
        page.add_row("Rangement automatique", "TriBin range tout seul les fichiers dont l'IA est assez sûre. "
                     "Les autres attendent votre avis : TriBin vous prévient.", self._auto_box(cfg))
        return page

    def _naming_box(self) -> QWidget:
        """Interrupteur « commencer par la date » et exemple de nom mis à jour en direct."""
        try:
            self.initial_date_prefix = has_date_prefix(self.c.service.convention())
        except Exception:
            self.initial_date_prefix = True
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.date_prefix = ToggleSwitch(self.initial_date_prefix)
        self.date_prefix.setAccessibleName("Commencer le nom par la date")
        row.addWidget(self.date_prefix)
        row.addWidget(QLabel("Commencer le nom par la date du document"), 1)
        layout.addLayout(row)
        self.name_example = QLabel()
        self.name_example.setFont(mono_font())
        layout.addWidget(self.name_example)
        if self.initial_mode == "work":
            layout.addWidget(muted("Modifie la convention de l'équipe : à décider ensemble."))
        self.date_prefix.toggled.connect(lambda _: self._naming_changed())
        self._naming_changed()
        return box

    def _naming_changed(self) -> None:
        self.name_example.setText("Exemple : " + ("2026-10-19_CV-ingenieur-IA.pdf" if self.date_prefix.isChecked()
                                                  else "CV-ingenieur-IA.pdf"))

    def _current_depth(self) -> int:
        try:
            return self.c.service.convention().structure.max_depth or PERSONAL_DEPTH
        except Exception:
            return PERSONAL_DEPTH

    def _depth_box(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(6)
        for depth in range(1, 6):
            button = QPushButton(f"{depth} niveau{'x' if depth > 1 else ''}")
            button.setObjectName("Chip")
            button.setCheckable(True)
            button.setChecked(depth == self.initial_depth)
            bold = button.font()
            bold.setBold(True)
            button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(button.text()) + 30)  # sélectionné : en gras
            self.depth_buttons.addButton(button, depth)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.depth_example = QLabel()
        self.depth_example.setFont(mono_font())
        self.depth_hint = muted()
        layout.addWidget(self.depth_example)
        layout.addWidget(self.depth_hint)
        self.depth_buttons.idClicked.connect(lambda _: self._depth_changed())
        self._depth_changed()
        return box

    def depth(self) -> int:
        return self.depth_buttons.checkedId() if self.depth_buttons.checkedId() > 0 else self.initial_depth

    def _depth_changed(self) -> None:
        depth = self.depth()
        self.depth_example.setText("Exemple : " + " › ".join(DEPTH_EXAMPLE[:depth]))
        self.depth_hint.setText({1: "Tous les fichiers d'une catégorie au même niveau.",
                                 2: "Un niveau de sous-dossiers : type de document."}.get(
            depth, "Recommandé : l'IA ne crée un sous-dossier que s'il regroupera des fichiers semblables."))

    def _auto_box(self, cfg) -> QWidget:
        """Interrupteur, curseur du seuil de confiance et phrase qui explique ce que fait ce seuil."""
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        switch_row = QHBoxLayout()
        switch_row.setSpacing(12)
        self.auto_file = ToggleSwitch(cfg.auto_file)
        self.auto_file.setAccessibleName("Rangement automatique")
        self.auto_state = QLabel()
        self.auto_state.setStyleSheet("font-weight: 600;")
        switch_row.addWidget(self.auto_file)
        switch_row.addWidget(self.auto_state, 1)
        layout.addLayout(switch_row)
        layout.addSpacing(4)
        layout.addWidget(section("Seuil de confiance"))
        self.threshold = ThresholdSlider(round((cfg.auto_min_confidence or AUTO_MIN_CONFIDENCE) * 100))
        layout.addWidget(self.threshold)
        scale = QHBoxLayout()
        for text in ("60 % · plus de fichiers rangés seuls", "95 % · seulement les plus sûrs"):
            label = muted(text, name="Faint", wrap=False)
            scale.addWidget(label)
            if text.startswith("60"):
                scale.addStretch()
        layout.addLayout(scale)
        self.threshold_hint = muted()
        layout.addWidget(self.threshold_hint)
        personal = self.initial_mode == "personal"
        layout.addWidget(muted(("En mode personnel, une catégorie ou un sous-dossier manquant (dans la limite de la "
                                "profondeur) est créé sans demander. " if personal else "Un fichier qui demanderait un nouveau dossier attend "
                                "toujours votre accord. ") + "Tout rangement s'annule depuis l'Historique."))
        self.auto_file.toggled.connect(lambda _: self._auto_changed())
        self.threshold.changed.connect(lambda _: self._auto_changed())
        self._auto_changed()
        return box

    def _auto_changed(self) -> None:
        on = self.auto_file.isChecked()
        value = self.threshold.value()
        self.auto_state.setText("Activé" if on else "Désactivé")
        self.threshold.setEnabled(on)
        if not on:
            self.threshold_hint.setText("Activez le rangement automatique pour régler le seuil.")
        elif value >= 80:
            self.threshold_hint.setText(f"Rangés seuls : les fichiers « sûrs » (confiance d'au moins {value} %).")
        else:
            self.threshold_hint.setText(f"Rangés seuls dès {value} % de confiance, y compris des fichiers « à "
                                        "regarder » : quelques erreurs possibles, toutes annulables.")

    def _ai_page(self) -> SettingsPage:
        svc = self.c.service
        ai_settings = svc.ai_settings()
        page = SettingsPage("Intelligence artificielle", "Le service qui propose le dossier et le nom de chaque fichier.")
        self.provider_group = QButtonGroup(self)
        self.provider_cards: dict[str, ChoiceCard] = {}
        cards = []
        for key, name, description, _, recommended in PROVIDERS:
            card = ChoiceCard(name, description, "Recommandé" if recommended else "")
            card.radio.setProperty("provider", key)
            card.radio.toggled.connect(lambda checked: checked and self._provider_changed())
            self.provider_group.addButton(card.radio)
            self.provider_cards[key] = card
            cards.append(card)
        page.add_row("Fournisseur", "Vous pouvez en changer à tout moment.", column(*cards))
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setMinimumWidth(260)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model)
        model_row.addStretch()
        page.add_row("Modèle", "Le modèle par défaut convient dans la plupart des cas.", column(model_row))
        self.api_key = ApiKeyField()
        page.add_row("Clé API", "Rangée dans le trousseau de l'ordinateur, jamais dans un fichier partagé.",
                     self.api_key)
        page.add_row("Confidentialité", "", muted(PRIVACY_NOTICE))
        current = ai_settings.provider if ai_settings.provider in self.provider_cards else "mistral"
        self.provider_cards[current].radio.setChecked(True)
        self._provider_changed()
        self.model.setCurrentText(svc.config.model or ai_settings.model)
        return page

    def _learning_page(self) -> SettingsPage:
        svc = self.c.service
        page = SettingsPage("Apprentissage", "Ce que TriBin sait de vous et ce qu'il a appris de vos corrections.")
        try:
            text = svc.settings.profile_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        self.profile = QPlainTextEdit(text)
        self.profile.setMinimumHeight(140)
        page.add_row("Profil", "Inclus dans chaque demande à l'IA. Modifiable librement.", self.profile)
        self.rules = QListWidget()
        self.rules.setMinimumHeight(160)
        self.rules.itemDoubleClicked.connect(self._edit_rule)
        del_rule = QPushButton("Supprimer la règle sélectionnée")
        del_rule.clicked.connect(self._delete_rule)
        widgets = [self.rules, del_rule]
        alerts = team_rule_alerts(svc.db)
        if alerts:
            warning = QLabel("\n".join(alerts) + "\nPensez à en parler au référent des conventions.")
            warning.setObjectName("Warning")
            warning.setWordWrap(True)
            widgets.insert(0, warning)
        page.add_row("Règles apprises", "Tirées de vos corrections. Double-clic pour en modifier une.", column(*widgets))
        self._load_rules()
        return page

    def _system_page(self) -> SettingsPage:
        journal_dir = self.c.service.settings.journal_dir
        page = SettingsPage("Système", "Raccourcis pour déposer des fichiers, et journal des opérations.")
        self.context_menu = QPushButton()
        self.context_menu.clicked.connect(self._toggle_context_menu)
        self.context_menu.setEnabled(sys.platform == "win32")
        self._refresh_context_menu()
        page.add_row("Clic droit", "« Trier avec TriBin » sur n'importe quel fichier. Sous Windows 11, Maj + clic droit "
                     "l'affiche directement (sinon : « Afficher d'autres options »).", column(self.context_menu))
        self.hotkey = QCheckBox(f"{HOTKEY_LABEL} envoie à TriBin les fichiers sélectionnés")
        self.hotkey.setChecked(self.c.service.config.hotkey)
        self.hotkey.setEnabled(sys.platform == "win32")
        page.add_row("Raccourci clavier", "Sélectionnez des fichiers dans l'Explorateur, puis appuyez sur "
                     f"{HOTKEY_LABEL} : ils partent dans TriBin, même si l'application est en arrière-plan.",
                     column(self.hotkey))
        sendto = QPushButton("Ajouter « Envoyer vers › TriBin » au clic droit")
        sendto.clicked.connect(lambda: self._integrate(system_integration.install_sendto))
        desktop = QPushButton("Créer un raccourci TriBin sur le bureau")
        desktop.clicked.connect(lambda: self._integrate(system_integration.install_desktop_shortcut))
        for button in (sendto, desktop):
            button.setEnabled(sys.platform == "win32")
        help_text = ("Glissez des fichiers sur le raccourci, ou faites un clic droit sur un fichier."
                     if sys.platform == "win32" else "Disponible sous Windows. Sous macOS, glissez sur l'icône du Dock.")
        page.add_row("Raccourcis", help_text, column(sendto, desktop))
        path = QLabel(str(journal_dir))
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_dir = QPushButton("Ouvrir le dossier")
        open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(journal_dir))))
        page.add_row("Journal des opérations", "Chaque opération y est notée avant d'être faite : il permet de "
                     "tout retrouver, même si l'application ne s'ouvre plus.", column(path, open_dir))
        return page

    # --- actions ------------------------------------------------------------------------------

    def mode(self) -> str:
        checked = self.mode_group.checkedButton()
        return checked.property("mode") if checked else "work"

    def provider(self) -> str:
        checked = self.provider_group.checkedButton()
        return checked.property("provider") if checked else "mistral"

    def _provider_changed(self) -> None:
        provider = self.provider()
        self.model.clear()
        self.model.addItems(MODELS[provider])
        _, name, _, console, _ = next(p for p in PROVIDERS if p[0] == provider)
        self.api_key.set_provider(name.split(" (")[0], console,
                                  self.c.service.settings.for_provider(provider).api_key)

    def _browse_convention(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Fichier de convention", self.convention.text(), "YAML (*.yaml *.yml)")
        if path:
            self.convention.setText(path)

    def _load_rules(self) -> None:
        self.rules.clear()
        for rule in list_rules(self.c.service.db):
            item = QListWidgetItem(rule.text)
            item.setData(Qt.ItemDataRole.UserRole, rule.id)
            self.rules.addItem(item)

    def _edit_rule(self, item: QListWidgetItem) -> None:
        text, ok = QInputDialog.getText(self, "Modifier la règle", "Règle :", text=item.text())
        if ok and text.strip():
            update_rule(self.c.service.db, item.data(Qt.ItemDataRole.UserRole), text)
            self._load_rules()

    def _delete_rule(self) -> None:
        for item in self.rules.selectedItems():
            delete_rule(self.c.service.db, item.data(Qt.ItemDataRole.UserRole))
        self._load_rules()

    def _refresh_context_menu(self) -> None:
        installed = system_integration.context_menu_installed()
        self.context_menu.setText("Retirer « Trier avec TriBin » du clic droit" if installed
                                  else "Ajouter « Trier avec TriBin » au clic droit")
        self.context_menu.setObjectName("" if installed else "Primary")
        self.context_menu.style().unpolish(self.context_menu)
        self.context_menu.style().polish(self.context_menu)

    def _toggle_context_menu(self) -> None:
        try:
            if system_integration.context_menu_installed():
                system_integration.uninstall_context_menu()
                QMessageBox.information(self, "TriBin", "« Trier avec TriBin » a été retiré du clic droit.")
            else:
                system_integration.install_context_menu()
                QMessageBox.information(self, "TriBin", "C'est prêt : faites Maj + clic droit sur un fichier, puis "
                                        "« Trier avec TriBin ».")
        except OSError as exc:
            QMessageBox.warning(self, "TriBin", f"Impossible de modifier le clic droit : {exc}")
        self._refresh_context_menu()

    def _integrate(self, fn) -> None:
        try:
            link = fn()
            QMessageBox.information(self, "TriBin", f"Raccourci créé : {link}")
        except Exception as exc:
            QMessageBox.warning(self, "TriBin", f"Impossible de créer le raccourci : {exc}")

    def _save(self) -> None:
        svc = self.c.service
        cfg = svc.config
        cfg.roots = self.roots.values()
        cfg.local_excluded = self.excluded.values()
        cfg.convention_path = self.convention.text().strip()
        mode = self.mode()
        if mode != self.initial_mode and cfg.roots:  # travail <-> personnel : convention du nouveau mode
            path, note = create_convention(mode, cfg.roots, svc.settings.data_dir)
            cfg.convention_path = str(path)
            QMessageBox.information(self, "TriBin", note)
        if self.initial_mode == "personal" and mode == "personal" and self.depth() != self.initial_depth:
            set_personal_depth(Path(cfg.convention_path), self.depth())
        self.naming_changed = self.date_prefix.isChecked() != self.initial_date_prefix and bool(cfg.convention_path)
        if self.naming_changed:
            set_date_prefix(Path(cfg.convention_path), self.date_prefix.isChecked())
        cfg.auto_file = self.auto_file.isChecked()
        cfg.auto_min_confidence = self.threshold.value() / 100
        cfg.hotkey = self.hotkey.isChecked()
        provider = self.provider()
        cfg.provider = provider
        cfg.model = self.model.currentText().strip()
        key = self.api_key.text().strip()
        if key:
            try:
                save_api_key(key, provider)
            except Exception as exc:
                QMessageBox.warning(self, "TriBin", f"Trousseau indisponible ({exc}) : clé utilisée pour cette session.")
            svc.settings = replace(svc.settings.for_provider(provider), api_key=key)
        save_profile(svc.settings.profile_path, self.profile.toPlainText())
        svc.update_config(cfg)
        self.accept()
