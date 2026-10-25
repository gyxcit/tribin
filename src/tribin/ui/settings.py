"""Réglages, rangés par catégories dans une colonne à gauche : Dossiers, Rangement, Autorisations,
Intelligence artificielle, Apprentissage, Système, Données. Chaque réglage : titre et aide à gauche, contrôle à droite."""

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
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tribin import resources
from tribin.config import save_api_key
from tribin.learning.corrections import team_rule_alerts
from tribin.service.bin import AUTO_MIN_CONFIDENCE
from tribin.convention.loader import PERSONAL_DEPTH
from tribin.service.conventions import (
    MODES,
    create_convention,
    current_mode,
    date_position,
    set_date_position,
    set_personal_depth,
)
from tribin.service.profile import save_profile
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

# Adresse de la page de confidentialité en ligne ; vide : page incluse dans TriBin
PRIVACY_URL = ""
PRIVACY_PAGE = Path(resources.__file__).with_name("confidentialite.html")


def open_privacy_policy() -> None:
    QDesktopServices.openUrl(QUrl(PRIVACY_URL) if PRIVACY_URL else QUrl.fromLocalFile(str(PRIVACY_PAGE)))


DEPTH_EXAMPLE = ["Etudes", "Certifications", "Universite", "Licence", "2026"]
MODELS = {"anthropic": ["claude-haiku-5-5", "claude-sonnet-5-5"],
          "gemini": ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest"],
          "mistral": ["mistral-medium-latest", "mistral-small-latest", "mistral-large-latest"]}
PAGES = (("folders", "Dossiers", "folder"), ("filing", "Rangement", "files"),
         ("permissions", "Autorisations", "shield"), ("ai", "Intelligence artificielle", "sparkle"),
         ("learning", "Apprentissage", "brain"), ("system", "Système", "monitor"),
         ("data", "Données", "database"))


class SettingsPage(QScrollArea):
    """Page de réglages : titre, phrase d'introduction, puis une ligne par réglage. `back` : lien « ‹ Page » au-dessus
    du titre, pour une sous-page (« Toutes les règles »)."""

    def __init__(self, title: str, lead: str = "", back: tuple[str, object] | None = None):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(32, 28, 32, 24)
        self.body.setSpacing(0)
        if back:
            label, slot = back
            link = QPushButton(label)
            link.setObjectName("Link")
            link.setIcon(line_icon("chevron-left", "#3B4CCA", 14))
            link.clicked.connect(slot)
            self.body.addWidget(link, 0, Qt.AlignmentFlag.AlignLeft)
            self.body.addSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("Title")
        self.body.addWidget(heading)
        if lead:
            self.body.addSpacing(4)
            self.body.addWidget(muted(lead))
        self.body.addSpacing(20)
        self.setWidget(content)

    def add_row(self, title: str, help_text: str, control: QWidget) -> QWidget:
        """Ajoute la ligne et la renvoie (pour la masquer selon le mode, par exemple)."""
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(divider())
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
        outer.addLayout(row)
        self.body.addWidget(container)
        return container

    def add_wide(self, title: str, help_text: str, control: QWidget) -> None:
        """Réglage sur toute la largeur (titre et aide au-dessus) : listes et grands champs."""
        self.body.addWidget(divider())
        self.body.addSpacing(18)
        self.body.addWidget(section(title))
        if help_text:
            self.body.addSpacing(2)
            self.body.addWidget(muted(help_text))
        self.body.addSpacing(12)
        self.body.addWidget(control)
        self.body.addSpacing(18)

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
        for build in (self._folders_page, self._filing_page, self._permissions_page, self._ai_page, self._learning_page,
                      self._system_page, self._data_page, self._all_rules_page):  # la dernière : sous-page, hors de la navigation
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
        page = SettingsPage("Dossiers")
        self.initial_mode = current_mode(self.c.service)
        self.mode_group = QButtonGroup(self)
        self.mode_cards: dict[str, ChoiceCard] = {}
        cards = []
        for key, title, _ in MODE_CHOICES:
            card = ChoiceCard(title, "")
            card.radio.setProperty("mode", key)
            self.mode_group.addButton(card.radio)
            self.mode_cards[key] = card
            cards.append(card)
        self.mode_cards[self.initial_mode].radio.setChecked(True)
        page.add_row("Utilisation", "", column(*cards))
        # dossiers de chaque mode, tels qu'affichés (changer de mode puis revenir ne perd rien)
        self.shown_mode = self.initial_mode
        self.mode_stash = {self.initial_mode: {"roots": list(cfg.roots), "local_excluded": list(cfg.local_excluded),
                                               "convention_path": cfg.convention_path}}
        for card in self.mode_cards.values():
            card.radio.toggled.connect(lambda checked: checked and self._mode_switched())
        self.roots = roots_picker(cfg.roots)
        remap = QPushButton("Réanalyser les dossiers")
        remap.setToolTip("Relit la structure des dossiers à ranger (après une réorganisation, par exemple).")
        remap.clicked.connect(self.c.remap)
        page.add_row("Dossiers à ranger", "", column(self.roots, remap))
        self.excluded = excluded_picker(cfg.local_excluded, self.roots.values)
        page.add_row("Dossiers à ne jamais toucher", "", self.excluded)
        return page

    def _filing_page(self) -> SettingsPage:
        """Comment ranger : convention de l'équipe (mode professionnel), nom des fichiers, profondeur des dossiers
        (mode personnel) et rangement automatique."""
        cfg = self.c.service.config
        page = SettingsPage("Rangement")
        conv_row = QHBoxLayout()
        self.convention = QLineEdit(cfg.convention_path)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse_convention)
        conv_row.addWidget(self.convention, 1)
        conv_row.addWidget(browse)
        # Fichier partagé par l'équipe ; en mode particulier, TriBin gère seul sa convention : rien à montrer.
        self.convention_row = page.add_row("Convention de l'équipe", "", column(conv_row))
        self.convention_row.setVisible(self.initial_mode == "work")
        page.add_row("Nom des fichiers", "", self._naming_box())
        self.depth_buttons = QButtonGroup(self)
        self.initial_depth = self._current_depth()
        if self.initial_mode == "personal":
            page.add_row("Profondeur des dossiers", "", self._depth_box())
        page.add_row("Rangement automatique", "", self._auto_box(cfg))
        return page

    def _naming_box(self) -> QWidget:
        """Interrupteurs « Commencer par la date » / « Terminer par la date » (l'un coupe l'autre ; les deux coupés :
        pas de date) et exemple de nom mis à jour en direct."""
        try:
            self.initial_date_position = date_position(self.c.service.convention())
        except Exception:
            self.initial_date_position = "start"
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.date_start = ToggleSwitch(self.initial_date_position == "start")
        self.date_end = ToggleSwitch(self.initial_date_position == "end")
        for switch, text in ((self.date_start, "Commencer par la date"), (self.date_end, "Terminer par la date")):
            switch.setAccessibleName(text)
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(switch)
            row.addWidget(QLabel(text), 1)
            layout.addLayout(row)
        self.name_example = QLabel()
        self.name_example.setFont(mono_font())
        layout.addWidget(self.name_example)
        if self.initial_mode == "work":
            layout.addWidget(muted("Modifie la convention de toute l'équipe."))
        self.date_start.toggled.connect(lambda on: self._date_switched(self.date_start, on))
        self.date_end.toggled.connect(lambda on: self._date_switched(self.date_end, on))
        self._naming_changed()
        return box

    def date_position(self) -> str:
        return "start" if self.date_start.isChecked() else "end" if self.date_end.isChecked() else "none"

    def _date_switched(self, switch: ToggleSwitch, on: bool) -> None:
        other = self.date_end if switch is self.date_start else self.date_start
        if on and other.isChecked():
            other.setChecked(False)  # une seule place pour la date
        self._naming_changed()

    def _naming_changed(self) -> None:
        self.name_example.setText("Exemple : " + {"start": "2026-10-19_CV-ingenieur-IA.pdf",
                                                  "end": "CV-ingenieur-IA_2026-10-19.pdf",
                                                  "none": "CV-ingenieur-IA.pdf"}[self.date_position()])

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
        self.depth_example.setWordWrap(True)  # sinon l'exemple à 5 niveaux élargit toute la colonne (et le curseur)
        layout.addWidget(self.depth_example)
        self.depth_buttons.idClicked.connect(lambda _: self._depth_changed())
        self._depth_changed()
        return box

    def depth(self) -> int:
        return self.depth_buttons.checkedId() if self.depth_buttons.checkedId() > 0 else self.initial_depth

    def _depth_changed(self) -> None:
        depth = self.depth()
        self.depth_example.setText("Exemple : " + " › ".join(DEPTH_EXAMPLE[:depth]))

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
        for text in ("60 % · plus de fichiers", "95 % · plus prudent"):
            label = muted(text, name="Faint", wrap=False)
            scale.addWidget(label)
            if text.startswith("60"):
                scale.addStretch()
        layout.addLayout(scale)
        self.threshold_hint = muted()
        layout.addWidget(self.threshold_hint)
        self.auto_file.toggled.connect(lambda _: self._auto_changed())
        self.threshold.changed.connect(lambda _: self._auto_changed())
        self._auto_changed()
        return box

    def _auto_changed(self) -> None:
        on = self.auto_file.isChecked()
        value = self.threshold.value()
        self.auto_state.setText("Activé" if on else "Désactivé")
        self.threshold.setEnabled(on)
        risky = on and value < 80
        self.threshold_hint.setText("Quelques erreurs possibles, toutes annulables depuis l'Historique."
                                    if risky else "")
        self.threshold_hint.setVisible(risky)

    def _permissions_page(self) -> SettingsPage:
        """Ce que TriBin peut faire seul, sans demander : un interrupteur et une phrase par autorisation."""
        page = SettingsPage("Autorisations")
        self.initial_create_folders = self.c.service.creates_folders()
        self.create_folders = ToggleSwitch(self.initial_create_folders)
        self.create_folders.setAccessibleName("Créer des dossiers")
        self.create_folders_state = QLabel()
        self.create_folders_state.setStyleSheet("font-weight: 600;")
        self.create_folders_hint = muted()
        switch_row = QHBoxLayout()
        switch_row.setSpacing(12)
        switch_row.addWidget(self.create_folders)
        switch_row.addWidget(self.create_folders_state, 1)
        page.add_row("Créer des dossiers", "", column(switch_row, self.create_folders_hint))
        self.create_folders.toggled.connect(lambda _: self._permissions_changed())
        self._permissions_changed()
        return page

    def _permissions_changed(self) -> None:
        on = self.create_folders.isChecked()
        self.create_folders_state.setText("Autorisé" if on else "Avec votre accord")
        self.create_folders_hint.setText(
            "TriBin crée seul les dossiers et sous-dossiers qu'il propose (« Design/Sarah-Mbossa »). "
            "Tout reste annulable depuis l'Historique." if on else
            "TriBin range dans les dossiers existants ; s'il en faut un nouveau, il vous le montre avant de le créer.")

    def _ai_page(self) -> SettingsPage:
        svc = self.c.service
        ai_settings = svc.ai_settings()
        page = SettingsPage("Intelligence artificielle")
        self.provider_group = QButtonGroup(self)
        self.provider_cards: dict[str, ChoiceCard] = {}
        cards = []
        for key, name, _, _, recommended in PROVIDERS:
            card = ChoiceCard(name, "", "Recommandé" if recommended else "")
            card.radio.setProperty("provider", key)
            card.radio.toggled.connect(lambda checked: checked and self._provider_changed())
            self.provider_group.addButton(card.radio)
            self.provider_cards[key] = card
            cards.append(card)
        page.add_row("Fournisseur", "", column(*cards))
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setMinimumWidth(260)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model)
        model_row.addStretch()
        page.add_row("Modèle", "", column(model_row))
        self.api_key = ApiKeyField()
        page.add_row("Clé API", "", self.api_key)
        privacy = QPushButton("Politique de confidentialité")
        privacy.setObjectName("Link")
        privacy.setIcon(line_icon("open", "#3B4CCA", 14))
        privacy.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        privacy.clicked.connect(open_privacy_policy)
        privacy_row = QHBoxLayout()  # à gauche comme les autres boutons (la flèche à droite inverse l'alignement)
        privacy_row.addWidget(privacy)
        privacy_row.addStretch()
        page.add_row("Confidentialité", "", column(privacy_row))
        current = ai_settings.provider if ai_settings.provider in self.provider_cards else "mistral"
        self.provider_cards[current].radio.setChecked(True)
        self._provider_changed()
        self.model.setCurrentText(svc.config.model or ai_settings.model)
        return page

    def _learning_page(self) -> SettingsPage:
        svc = self.c.service
        page = SettingsPage("Apprentissage")
        try:
            text = svc.settings.profile_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        self.profile = QPlainTextEdit(text)
        self.profile.setMinimumHeight(140)
        page.add_row("Profil", "Envoyé à l'IA avec chaque fichier.", self.profile)
        from tribin.ui.rules_view import RulesEditor

        alerts = team_rule_alerts(svc.db) if self.initial_mode == "work" else []  # pas d'équipe en mode personnel
        if alerts:
            warning = QLabel("\n".join(alerts) + "\nPensez à en parler au référent des conventions.")
            warning.setObjectName("Warning")
            warning.setWordWrap(True)
            page.add_wide("Règles d'équipe souvent corrigées", "", warning)
        self.rules = RulesEditor(self.c)
        self.rules.show_all.connect(self.show_all_rules)
        page.add_wide("Règles", "", self.rules)
        return page

    def _all_rules_page(self) -> SettingsPage:
        from tribin.ui.rules_view import RulesBrowser

        page = SettingsPage("Toutes les règles", back=("Apprentissage", self._back_to_learning))
        self.rules_browser = RulesBrowser(self.c)
        page.body.addWidget(self.rules_browser)
        return page

    def show_all_rules(self, kind: str = "learned") -> None:
        self.rules_browser.search.clear()
        self.rules_browser.show_kind(kind)
        self.pages.setCurrentIndex(len(PAGES))

    def _back_to_learning(self) -> None:
        self.rules.reload()  # règles modifiées, ajoutées ou supprimées sur la page « Toutes les règles »
        index = [key for key, *_ in PAGES].index("learning")
        self.nav.button(index).setChecked(True)
        self.pages.setCurrentIndex(index)

    def _system_page(self) -> SettingsPage:
        page = SettingsPage("Système")
        self.context_menu = QPushButton()
        self.context_menu.clicked.connect(self._toggle_context_menu)
        self.context_menu.setEnabled(sys.platform == "win32")
        self._refresh_context_menu()
        page.add_row("Clic droit", "Windows 11 : Maj + clic droit pour l'afficher directement.",
                     column(self.context_menu))
        self.hotkey = QCheckBox(f"{HOTKEY_LABEL} envoie à TriBin les fichiers sélectionnés")
        self.hotkey.setChecked(self.c.service.config.hotkey)
        self.hotkey.setEnabled(sys.platform == "win32")
        page.add_row("Raccourci clavier", "", column(self.hotkey))
        sendto = QPushButton("Ajouter « Envoyer vers › TriBin » au clic droit")
        sendto.clicked.connect(lambda: self._integrate(system_integration.install_sendto))
        desktop = QPushButton("Créer un raccourci TriBin sur le bureau")
        desktop.clicked.connect(lambda: self._integrate(system_integration.install_desktop_shortcut))
        for button in (sendto, desktop):
            button.setEnabled(sys.platform == "win32")
        page.add_row("Raccourcis", "" if sys.platform == "win32" else "Disponible sous Windows.",
                     column(sendto, desktop))
        return page

    def _data_page(self) -> SettingsPage:
        """Fichiers que TriBin tient à jour sur ce poste : où ils sont, et un bouton pour les ouvrir."""
        settings = self.c.service.settings
        page = SettingsPage("Données")
        page.add_row("Journal des opérations", "", self._folder_box(settings.journal_dir))
        page.add_row("Dossier de TriBin", "Réglages, règles, profil et conventions.", self._folder_box(settings.data_dir))
        return page

    @staticmethod
    def _folder_box(folder: Path) -> QWidget:
        path = QLabel(str(folder))
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_dir = QPushButton("Ouvrir le dossier")
        open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))
        return column(path, open_dir)

    # --- actions ------------------------------------------------------------------------------

    def _mode_switched(self) -> None:
        """Particulier <-> Professionnel : affiche les dossiers et la convention du mode choisi."""
        new = self.mode()
        if new == self.shown_mode or not hasattr(self, "convention"):
            return
        self.mode_stash[self.shown_mode] = {"roots": self.roots.values(), "local_excluded": self.excluded.values(),
                                            "convention_path": self.convention.text().strip()}
        values = self.mode_stash.get(new) or self.c.service.config.mode_values(new)
        self.roots.set_values(values["roots"])
        self.excluded.set_values(values["local_excluded"])
        self.convention.setText(values["convention_path"])
        self.convention_row.setVisible(new == "work")
        self.shown_mode = new

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
        mode = self.mode()
        roots = self.roots.values()
        if not roots:
            QMessageBox.information(self, "TriBin", f"Choisissez au moins un dossier à ranger pour le mode "
                                    f"{MODES[mode]} (Réglages › Dossiers).")
            return
        if mode != self.initial_mode:  # l'ancien mode garde ses dossiers et sa convention
            old = self.mode_stash.get(self.initial_mode) or {}
            cfg.by_mode[self.initial_mode] = {"roots": old.get("roots", cfg.roots),
                                              "local_excluded": old.get("local_excluded", cfg.local_excluded),
                                              "convention_path": old.get("convention_path", cfg.convention_path)}
        cfg.roots = roots
        cfg.local_excluded = self.excluded.values()
        cfg.convention_path = self.convention.text().strip()
        missing = not (cfg.convention_path and Path(cfg.convention_path).is_file())
        if missing and (mode != self.initial_mode or mode == "personal"):
            # première utilisation du mode, ou convention personnelle disparue (aucun champ pour la corriger)
            path, note = create_convention(mode, cfg.roots, svc.settings.data_dir)
            cfg.convention_path = str(path)
            QMessageBox.information(self, "TriBin", note)
        cfg.remember_mode(mode)
        if self.initial_mode == "personal" and mode == "personal" and self.depth() != self.initial_depth:
            set_personal_depth(Path(cfg.convention_path), self.depth())
        self.naming_changed = self.date_position() != self.initial_date_position and bool(cfg.convention_path)
        if self.naming_changed:
            set_date_position(Path(cfg.convention_path), self.date_position())
        if self.create_folders.isChecked() != self.initial_create_folders:  # sinon : le réglage par défaut du mode
            cfg.auto_create_folders = self.create_folders.isChecked()
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
