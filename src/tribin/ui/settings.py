"""Réglages : racines, zones exclues, convention, profil, règles apprises, modèle, clé API, confidentialité."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
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

if TYPE_CHECKING:
    from tribin.ui.app import AppController

MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]


def path_list(items: list[str]) -> tuple[QWidget, QListWidget]:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    lst = QListWidget()
    lst.addItems(items)
    row = QHBoxLayout()
    add, remove = QPushButton("Ajouter…"), QPushButton("Retirer")

    def on_add() -> None:
        folder = QFileDialog.getExistingDirectory(box, "Choisir un répertoire de référence")
        if folder and not lst.findItems(folder, Qt.MatchFlag.MatchExactly):
            lst.addItem(str(Path(folder)))

    add.clicked.connect(on_add)
    remove.clicked.connect(lambda: [lst.takeItem(lst.row(i)) for i in lst.selectedItems()])
    row.addWidget(add)
    row.addWidget(remove)
    row.addStretch()
    layout.addWidget(lst)
    layout.addLayout(row)
    return box, lst


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
        roots_box, self.roots = path_list(cfg.roots)
        form.addRow("Répertoires de référence (racines)", roots_box)
        self.excluded = QPlainTextEdit("\n".join(cfg.local_excluded))
        self.excluded.setPlaceholderText("Un motif par ligne, relatif à la racine, ex. **/_PROJET_EN_COURS/**")
        form.addRow("Zones exclues (en plus de la convention)", self.excluded)
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
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(MODELS)
        self.model.setCurrentText(cfg.model or svc.settings.model)
        af.addRow("Modèle d'IA", self.model)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("déjà enregistrée" if svc.settings.api_key else "sk-ant-…")
        af.addRow("Clé API Anthropic (trousseau système)", self.api_key)
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
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

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
        cfg.roots = [self.roots.item(i).text() for i in range(self.roots.count())]
        cfg.local_excluded = [line.strip() for line in self.excluded.toPlainText().splitlines() if line.strip()]
        cfg.convention_path = self.convention.text().strip()
        cfg.model = self.model.currentText().strip()
        key = self.api_key.text().strip()
        if key:
            try:
                save_api_key(key)
            except Exception as exc:
                QMessageBox.warning(self, "TriBin", f"Trousseau indisponible ({exc}) : clé utilisée pour cette session.")
            svc.settings = replace(svc.settings, api_key=key)
        save_profile(svc.settings.profile_path, self.profile.toPlainText())
        svc.update_config(cfg)
        self.accept()
