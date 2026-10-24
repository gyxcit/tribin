"""Icône dans la barre système (barre des menus macOS, zone de notification Windows) avec compteur."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from tribin.ui.icons import app_icon

if TYPE_CHECKING:
    from tribin.ui.app import AppController


class Tray(QSystemTrayIcon):
    def __init__(self, controller: AppController):
        super().__init__(app_icon())
        self.c = controller
        menu = QMenu()
        for label, slot in [("Corbeille", controller.show_bin), ("Historique", controller.show_history),
                            ("Réglages", controller.show_settings)]:
            action = QAction(label, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        self.toggle_widget = QAction("Afficher le widget de dépôt", menu, checkable=True, checked=True)
        self.toggle_widget.toggled.connect(controller.set_drop_widget_visible)
        menu.addAction(self.toggle_widget)
        menu.addSeparator()
        quit_action = QAction("Quitter", menu)
        quit_action.triggered.connect(controller.quit)
        menu.addAction(quit_action)
        self._menu = menu
        self.setContextMenu(menu)
        self.activated.connect(self._activated)
        self.set_count(0)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.c.show_bin()

    def set_count(self, count: int) -> None:
        self.setIcon(app_icon(count))
        self.setToolTip(f"TriBin — {count} fichier(s) en attente" if count else "TriBin — aucun fichier en attente")
