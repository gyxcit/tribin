"""Panneau de détail de la Corbeille : le fichier sélectionné, sa proposition modifiable et les actions."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QFileInfo, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QFileIconProvider,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tribin.service.queue import QueueItem
from tribin.ui.theme import pill_colors, pill_style

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


PREVIEW_EXT = {".pdf", ".ai", ".psd"}


@lru_cache(maxsize=256)
def _preview_bytes(path: str, mtime: float, size: int) -> bytes | None:
    """Aperçu JPEG d'un PDF, AI ou PSD (mis en cache tant que le fichier ne change pas)."""
    from tribin.extract import extract

    try:
        info = extract(Path(path))
    except Exception:
        return None
    if info.images:
        return info.images[0]
    if Path(path).suffix.lower() in {".pdf", ".ai"}:
        from tribin.extract.pdf import render_first_page

        return render_first_page(Path(path))
    return None


def thumbnail(path: Path, size: int) -> QPixmap:
    """Miniature d'une image, aperçu d'un PDF/AI/PSD, sinon l'icône du type de fichier."""
    suffix = path.suffix.lower()
    pix = QPixmap()
    if suffix in IMAGE_EXT and path.exists():
        pix = QPixmap(str(path))
    elif suffix in PREVIEW_EXT and path.exists():
        data = _preview_bytes(str(path), path.stat().st_mtime, path.stat().st_size)
        if data:
            pix.loadFromData(data)
    if not pix.isNull():
        return pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return QFileIconProvider().icon(QFileInfo(str(path))).pixmap(size, size)


def elided(text: str, widget: QWidget, width: int, mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> str:
    return QFontMetrics(widget.font()).elidedText(text, mode, width)


def short_confidence(item: QueueItem) -> str:
    """Version courte pour la liste : « 92 % », « Analyse… », « À traiter »."""
    if item.status == "analyzing":
        return "Analyse…"
    if item.status == "error" or not item.proposal or item.proposal.manual:
        return "À traiter"
    return f"{item.proposal.confidence:.0%}"


def confidence_text(item: QueueItem) -> str:
    if item.status == "analyzing":
        return "Analyse…"
    if item.status == "error":
        return "Erreur"
    p = item.proposal
    if p is None or p.manual:
        return "À traiter"
    if p.needs_review:
        return f"À vérifier · {p.confidence:.0%}"
    return f"{p.confidence:.0%}"


def item_pill(item: QueueItem) -> tuple[str, str]:
    p = item.proposal
    return pill_colors(p.confidence if p else None, manual=bool(p and p.manual) or item.status == "error",
                       waiting=item.status == "analyzing")


def section(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("Section")
    return label


class DetailPanel(QFrame):
    """Proposition du fichier sélectionné ; le nom et le dossier se modifient directement."""

    edited = Signal()
    alternative_chosen = Signal(int)
    validate_clicked = Signal()
    return_clicked = Signal()
    skip_clicked = Signal()
    browse_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.item: QueueItem | None = None
        self._filling = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.thumb = QLabel()
        self.thumb.setFixedSize(96, 96)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background: #F5F6FA; border-radius: 8px;")
        top.addWidget(self.thumb)
        heading = QVBoxLayout()
        self.original = QLabel()
        self.original.setObjectName("Big")
        self.original.setWordWrap(True)
        self.origin_path = QLabel()
        self.origin_path.setObjectName("Muted")
        self.pill = QLabel()
        self.pill.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        heading.addWidget(self.original)
        heading.addWidget(self.origin_path)
        heading.addWidget(self.pill)
        heading.addStretch()
        top.addLayout(heading, 1)
        layout.addLayout(top)
        layout.addSpacing(8)

        layout.addWidget(section("Nouveau nom"))
        self.name = QLineEdit()
        self.name.textChanged.connect(self._changed)
        self.name.returnPressed.connect(self.validate_clicked)
        layout.addWidget(self.name)
        layout.addWidget(section("Dossier de rangement"))
        folder_row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.textChanged.connect(self._changed)
        self.folder.returnPressed.connect(self.validate_clicked)
        self.browse = QPushButton("Parcourir…")
        self.browse.clicked.connect(self.browse_clicked)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(self.browse)
        layout.addLayout(folder_row)
        self.new_folder = QLabel("Ce dossier sera créé (la simulation te sera montrée avant).")
        self.new_folder.setObjectName("Muted")
        layout.addWidget(self.new_folder)

        layout.addWidget(section("Pourquoi"))
        self.reasoning = QLabel()
        self.reasoning.setWordWrap(True)
        layout.addWidget(self.reasoning)
        self.warnings = QLabel()
        self.warnings.setObjectName("Warning")
        self.warnings.setWordWrap(True)
        layout.addWidget(self.warnings)

        self.alt_title = section("Autres pistes")
        layout.addWidget(self.alt_title)
        self.alt_box = QWidget()
        self.alt_layout = QVBoxLayout(self.alt_box)
        self.alt_layout.setContentsMargins(0, 0, 0, 0)
        self.alt_layout.setSpacing(4)
        layout.addWidget(self.alt_box)
        layout.addStretch()

        actions = QHBoxLayout()
        self.validate_button = QPushButton("Valider et ranger  ⏎")
        self.validate_button.setObjectName("Primary")
        self.validate_button.clicked.connect(self.validate_clicked)
        self.return_button = QPushButton("Renvoyer à l'origine  (R)")
        self.return_button.clicked.connect(self.return_clicked)
        self.skip_button = QPushButton("Passer  (Échap)")
        self.skip_button.clicked.connect(self.skip_clicked)
        actions.addWidget(self.validate_button)
        actions.addWidget(self.return_button)
        actions.addStretch()
        actions.addWidget(self.skip_button)
        layout.addLayout(actions)

    def _changed(self) -> None:
        if not self._filling:
            self.edited.emit()

    def show_item(self, item: QueueItem | None, name: str = "", folder: str = "") -> None:
        """Affiche un fichier ; `name` et `folder` : valeurs en cours (éventuellement modifiées)."""
        self.item = item
        self._filling = True
        try:
            if item is None:
                self.setVisible(False)
                return
            self.setVisible(True)
            p = item.proposal
            ready = item.status == "ready" and p is not None
            self.thumb.setPixmap(thumbnail(Path(item.staged_path), 88))
            self.original.setText(Path(item.original_path).name)
            origin = f"Venait de : {Path(item.original_path).parent}"
            self.origin_path.setText(elided(origin, self.origin_path, 420, Qt.TextElideMode.ElideMiddle))
            self.origin_path.setToolTip(str(Path(item.original_path).parent))
            self.pill.setText(confidence_text(item))
            self.pill.setStyleSheet(pill_style(item_pill(item)))
            self.name.setText(name)
            self.folder.setText(folder)
            self.name.setEnabled(ready)  # une proposition « à traiter » se complète à la main
            self.folder.setEnabled(ready)
            self.browse.setEnabled(ready)
            self.validate_button.setEnabled(ready)
            self.new_folder.setVisible(bool(p and p.folder_is_new and folder == p.target_folder))
            if item.status == "analyzing":
                self.reasoning.setText("L'IA analyse ce fichier…")
            elif item.status == "error":
                self.reasoning.setText(item.error or "Erreur pendant l'analyse.")
            else:
                self.reasoning.setText(p.reasoning if p and p.reasoning else "—")
            warnings = list(p.warnings) if p else []
            if item.error and item.status == "ready":
                warnings.append(item.error)
            self.warnings.setText("\n".join(f"⚠ {w}" for w in warnings))
            self.warnings.setVisible(bool(warnings))
            self._fill_alternatives(item)
        finally:
            self._filling = False

    def _fill_alternatives(self, item: QueueItem) -> None:
        while self.alt_layout.count():
            widget = self.alt_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        alternatives = item.proposal.alternatives if item.proposal else []
        self.alt_title.setVisible(bool(alternatives))
        for index, alt in enumerate(alternatives):
            chip = QPushButton(f"{alt.target_folder}/{alt.new_name}")
            chip.setObjectName("Chip")
            chip.setFixedHeight(28)
            chip.setToolTip(alt.reasoning or "")
            chip.clicked.connect(lambda _=False, i=index: self.alternative_chosen.emit(i))
            self.alt_layout.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)
            chip.show()  # ajouté à un panneau déjà visible : à afficher explicitement
