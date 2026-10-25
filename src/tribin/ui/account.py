"""Compte (bas de la navigation) : avatar, nom, statut ; fenêtre pour le modifier."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from tribin.service.account import Account, get_account, save_account
from tribin.ui.components import muted

if TYPE_CHECKING:
    from tribin.ui.app import AppController


def avatar(account: Account, size: int = 32) -> QLabel:
    label = QLabel(account.initials)
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(f"background: #1F2544; color: white; border-radius: {size // 2}px; "
                        f"font-weight: 700; font-size: {max(11, size // 3)}px;")
    return label


class AccountChip(QFrame):
    """Bas de la navigation : avatar, nom et « Compte local » ; un clic ouvre le compte."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("AccountChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Votre compte TriBin")
        self.setStyleSheet("QFrame#AccountChip { border-radius: 8px; background: transparent; }"
                           "QFrame#AccountChip:hover { background: #ECEEF6; }"
                           "QFrame#AccountChip QLabel { background: transparent; }")
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(8, 8, 8, 8)
        self.row.setSpacing(10)
        self.avatar = QLabel()
        self.row.addWidget(self.avatar)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.name = QLabel()
        self.name.setStyleSheet("font-weight: 600;")
        self.status = muted(wrap=False)
        self.status.setStyleSheet("font-size: 12px;")
        texts.addWidget(self.name)
        texts.addWidget(self.status)
        self.row.addLayout(texts, 1)

    def set_account(self, account: Account) -> None:
        new_avatar = avatar(account, 32)
        self.row.replaceWidget(self.avatar, new_avatar)
        self.avatar.hide()
        self.avatar.deleteLater()
        self.avatar = new_avatar
        self.name.setText(account.display_name)
        self.status.setText(account.status)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — API Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class AccountDialog(QDialog):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        db = controller.service.db
        account = get_account(db, controller.service.settings.user)
        self.setWindowTitle("TriBin — Compte")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(avatar(account, 56))
        titles = QVBoxLayout()
        title = QLabel(account.display_name)
        title.setObjectName("Title")
        titles.addWidget(title)
        titles.addWidget(muted(f"{account.status} · créé le {account.created_at[:10]}", wrap=False))
        head.addLayout(titles, 1)
        layout.addLayout(head)

        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit(account.display_name)
        self.email = QLineEdit(account.email)
        self.email.setPlaceholderText("vous@exemple.fr (facultatif)")
        form.addRow("Nom", self.name)
        form.addRow("Adresse e-mail", self.email)
        layout.addLayout(form)

        note = QFrame()
        note.setStyleSheet("QFrame { background: #F6F7FB; border: 1px solid #E2E5EF; border-radius: 10px; }"
                           "QLabel { background: transparent; border: none; }")
        box = QVBoxLayout(note)
        box.setContentsMargins(14, 12, 14, 12)
        heading = QLabel("Connexion aux serveurs TriBin : bientôt")
        heading.setStyleSheet("font-weight: 600;")
        box.addWidget(heading)
        box.addWidget(muted("Votre compte et vos données (réglages, file d'attente, règles apprises) restent pour "
                            "l'instant sur cet ordinateur, dans une base locale :"))
        path = QLabel(str(db.path))
        path.setStyleSheet("font-size: 12px; color: #3A4063;")
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setWordWrap(True)
        box.addWidget(path)
        layout.addWidget(note)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Enregistrer")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        save_account(self.c.service.db, self.name.text(), self.email.text())
        self.accept()
