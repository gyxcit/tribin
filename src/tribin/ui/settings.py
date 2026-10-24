"""Réglages : racines, zones exclues, convention, profil, règles apprises, modèle, clé API, confidentialité."""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tribin.config import save_api_key
from tribin.learning.corrections import team_rule_alerts
from tribin.learning.rules_store import delete_rule, list_rules, update_rule
from tribin.service.profile import PRIVACY_NOTICE, save_profile
from tribin.ui import system_integration
from tribin.ui.folder_picker import excluded_picker, roots_picker
from tribin.ui.theme import header_bar

if TYPE_CHECKING:
    from tribin.ui.app import AppController

MODELS = {"anthropic": ["claude-haiku-5-5", "claude-sonnet-5-5"],
          "gemini": ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest"],
          "mistral": ["mistral-medium-latest", "mistral-small-latest", "mistral-large-latest"]}
PROVIDER_LABELS = {"anthropic": "Anthropic (Claude)", "gemini": "Google (Gemini)", "mistral": "Mistral AI"}


class SettingsDialog(QDialog):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        svc = controller.service
        cfg = svc.config
        self.setWindowTitle("TriBin — Réglages")
        self.resize(760, 560)
        tabs = QTabWidget()

        general = QWidget()
        form = QFormLayout(general)
        self.roots = roots_picker(cfg.roots)
        form.addRow("Dossiers à ranger", self.roots)
        self.excluded = excluded_picker(cfg.local_excluded, self.roots.values)
        form.addRow("Dossiers à ne jamais toucher", self.excluded)
        conv_row = QHBoxLayout()
        self.convention = QLineEdit(cfg.convention_path)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse_convention)
        conv_row.addWidget(self.convention)
        conv_row.addWidget(browse)
        form.addRow("Fichier de convention (local ou NAS)", conv_row)
        remap = QPushButton("Recartographier les racines")
        remap.clicked.connect(self.c.remap)
        form.addRow("", remap)
        tabs.addTab(general, "Général")

        profile_tab = QWidget()
        pl = QVBoxLayout(profile_tab)
        pl.addWidget(QLabel("Profil (inclus dans chaque demande à l'IA) :"))
        try:
            text = svc.settings.profile_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        self.profile = QPlainTextEdit(text)
        pl.addWidget(self.profile)
        pl.addWidget(QLabel("Règles apprises de tes corrections (double-clic pour modifier) :"))
        self.rules = QListWidget()
        self.rules.itemDoubleClicked.connect(self._edit_rule)
        pl.addWidget(self.rules)
        del_rule = QPushButton("Supprimer la règle")
        del_rule.clicked.connect(self._delete_rule)
        pl.addWidget(del_rule)
        alerts = team_rule_alerts(svc.db)
        if alerts:
            warning = QLabel("\n".join(alerts) + "\nPense à en parler au référent des conventions.")
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #b7791f;")
            pl.addWidget(warning)
        self._load_rules()
        tabs.addTab(profile_tab, "Profil et apprentissage")

        ai = QWidget()
        af = QFormLayout(ai)
        ai_settings = svc.ai_settings()
        self.provider = QComboBox()
        for key, label in PROVIDER_LABELS.items():
            self.provider.addItem(label, key)
        self.provider.setCurrentIndex(list(PROVIDER_LABELS).index(ai_settings.provider))
        af.addRow("Fournisseur d'IA", self.provider)
        self.model = QComboBox()
        self.model.setEditable(True)
        af.addRow("Modèle d'IA", self.model)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        af.addRow("Clé API (trousseau système)", self.api_key)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed()
        self.model.setCurrentText(cfg.model or ai_settings.model)
        notice = QLabel(PRIVACY_NOTICE)
        notice.setWordWrap(True)
        af.addRow(notice)
        tabs.addTab(ai, "IA et confidentialité")

        system = QWidget()
        sl = QVBoxLayout(system)
        sendto = QPushButton("Ajouter « Envoyer vers > TriBin » (clic droit, Windows)")
        sendto.clicked.connect(lambda: self._integrate(system_integration.install_sendto))
        desktop = QPushButton("Créer un raccourci TriBin sur le bureau (y glisser des fichiers)")
        desktop.clicked.connect(lambda: self._integrate(system_integration.install_desktop_shortcut))
        for btn in (sendto, desktop):
            btn.setEnabled(sys.platform == "win32")
            sl.addWidget(btn)
        journal = QLabel(f"Journal des opérations (à retrouver en urgence) :\n{svc.settings.journal_dir}")
        journal.setWordWrap(True)
        journal.setTextInteractionFlags(journal.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        sl.addWidget(journal)
        sl.addStretch()
        tabs.addTab(system, "Système")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Enregistrer")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(header_bar("Réglages", "Racines, convention, IA et intégration au système"))
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(body, 1)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _provider_changed(self) -> None:
        provider = self.provider.currentData()
        self.model.clear()
        self.model.addItems(MODELS[provider])
        has_key = bool(self.c.service.settings.for_provider(provider).api_key)
        self.api_key.setPlaceholderText("déjà enregistrée" if has_key else ({"anthropic": "sk-ant-…"}.get(provider, f"clé {PROVIDER_LABELS[provider]}")))

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
        provider = self.provider.currentData()
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
