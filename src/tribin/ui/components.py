"""Composants visuels réutilisables : titres, pastilles, barre de confiance, fil d'Ariane, boutons, aperçus."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFileIconProvider,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tribin.service.queue import QueueItem
from tribin.ui.theme import level_for, pill_style

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
PREVIEW_EXT = {".pdf", ".ai", ".psd"}

# Couleur du badge de type de fichier (liste et en-tête du détail)
BADGE_COLORS = {".pdf": "#C2410C", ".psd": "#2C3460", ".ai": "#B45309", ".indd": "#BE185D",
                ".jpg": "#6B7194", ".jpeg": "#6B7194", ".png": "#7C3AED", ".gif": "#7C3AED", ".svg": "#7C3AED",
                ".doc": "#3B47B8", ".docx": "#3B47B8", ".xls": "#0F766E", ".xlsx": "#0F766E", ".csv": "#0F766E",
                ".ppt": "#C2410C", ".pptx": "#C2410C", ".zip": "#5B6080", ".mp4": "#9D174D", ".mov": "#9D174D"}

# Statut affiché dans la file : clé de niveau -> libellé court
STATUS_LABELS = {"sure": "Prêt", "look": "À regarder", "check": "À vérifier", "wait": "Analyse"}


# --- textes -----------------------------------------------------------------------------------


def section(text: str, name: str = "Section") -> QLabel:
    """Titre de section, en minuscules comme une phrase (« Dossiers à ranger »)."""
    label = QLabel(text)
    label.setObjectName(name)
    return label


def muted(text: str = "", name: str = "Muted", wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    return line


def elided(text: str, widget: QWidget, width: int, mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> str:
    return QFontMetrics(widget.font()).elidedText(text, mode, width)


def item_level(item: QueueItem) -> tuple[str, str, str, str]:
    """Niveau de confiance d'un fichier en attente (analyse en cours, erreur, manuel compris)."""
    p = item.proposal
    return level_for(p.confidence if p else None, manual=bool(p and p.manual) or item.status == "error",
                     waiting=item.status == "analyzing")


def status_label(item: QueueItem) -> str:
    """Pastille de la file : « Prêt », « À regarder », « À vérifier », « Analyse »."""
    return STATUS_LABELS[item_level(item)[0]]


def human_size(size: int) -> str:
    for unit in ("octets", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{size:.0f} {unit}" if unit == "octets" else f"{size:.1f} {unit}".replace(".", ",")
        size /= 1024
    return ""


class Pill(QLabel):
    """Pastille colorée (niveau de confiance ou statut)."""

    def __init__(self, text: str = "", colors: tuple[str, str] = ("#ECEEF4", "#5B6080")):
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_colors(colors)

    def set_colors(self, colors: tuple[str, str]) -> None:
        self.setStyleSheet(pill_style(colors))


class FileBadge(QLabel):
    """Carré coloré avec l'extension du fichier (« PDF », « PSD »…)."""

    def __init__(self, size: int = 36):
        super().__init__()
        self.setObjectName("FileBadge")
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_path(self, path: Path) -> None:
        suffix = path.suffix.lower()
        self.setText((suffix[1:4] or "?").upper())
        self.setStyleSheet(f"background: {BADGE_COLORS.get(suffix, '#5B6080')};")


class ChoiceCard(QFrame):
    """Carte cliquable avec bouton radio, titre, étiquette facultative et une ligne d'explication."""

    def __init__(self, title: str, description: str, tag: str = ""):
        super().__init__()
        self.setObjectName("ChoiceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(10)
        self.radio = QRadioButton()
        self.radio.toggled.connect(self._toggled)
        row.addWidget(self.radio, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(title)
        name.setStyleSheet("font-weight: 600;")
        head.addWidget(name)
        if tag:
            badge = QLabel(tag)
            badge.setStyleSheet("background: #DDF5F1; color: #0F766E; border-radius: 9px; padding: 1px 8px;"
                                " font-size: 11px; font-weight: 600;")
            head.addWidget(badge)
        head.addStretch()
        texts.addLayout(head)
        texts.addWidget(muted(description))
        row.addLayout(texts, 1)

    def mousePressEvent(self, event) -> None:  # noqa: N802 — API Qt
        self.radio.setChecked(True)

    def _toggled(self, checked: bool) -> None:
        self.setProperty("checked", "true" if checked else "false")
        self.style().unpolish(self)
        self.style().polish(self)


# --- clé API ---------------------------------------------------------------------------------------


def masked_key(key: str) -> str:
    """« ••••3fQ2 » : seuls les 4 derniers caractères, pour reconnaître la clé sans l'exposer."""
    return "••••" + key[-4:] if len(key) > 8 else "••••"


class ApiKeyField(QWidget):
    """Clé API : état bien visible (« ✓ Clé enregistrée ») avec « Remplacer », sinon champ de saisie.

    `text()` renvoie la nouvelle clé saisie (vide : garder la clé enregistrée)."""

    def __init__(self) -> None:
        super().__init__()
        self.saved = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.status = QFrame()
        self.status.setObjectName("KeyStatus")
        row = QHBoxLayout(self.status)
        row.setContentsMargins(12, 10, 10, 10)
        row.setSpacing(10)
        check = QLabel("✓")
        check.setObjectName("KeyCheck")
        check.setFixedSize(22, 22)
        check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.status_title = QLabel()
        self.status_title.setStyleSheet("font-weight: 600; color: #0F766E;")
        self.status_detail = QLabel()
        self.status_detail.setObjectName("Muted")
        texts.addWidget(self.status_title)
        texts.addWidget(self.status_detail)
        self.replace_button = QPushButton("Remplacer la clé")
        self.replace_button.clicked.connect(lambda: self._editing(True))
        row.addWidget(check, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(texts, 1)
        row.addWidget(self.replace_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.status)

        self.editor = QWidget()
        edit_row = QHBoxLayout(self.editor)
        edit_row.setContentsMargins(0, 0, 0, 0)
        edit_row.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("Collez votre clé ici")
        self.show_key = QPushButton("Afficher")
        self.show_key.setObjectName("Link")
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(self._show)
        self.cancel = QPushButton("Garder l'ancienne")
        self.cancel.setObjectName("Link")
        self.cancel.clicked.connect(lambda: self._editing(False))
        edit_row.addWidget(self.edit, 1)
        edit_row.addWidget(self.show_key)
        edit_row.addWidget(self.cancel)
        layout.addWidget(self.editor)

        self.hint = muted()
        layout.addWidget(self.hint)

    def set_provider(self, name: str, console: str, saved_key: str | None) -> None:
        self.saved = saved_key or ""
        self.edit.clear()
        self.status_title.setText(f"Clé {name} enregistrée sur cet ordinateur")
        self.status_detail.setText(f"Se termine par {masked_key(self.saved)}. Rien d'autre à faire.")
        self.console = console
        self._editing(not self.saved)

    def _editing(self, editing: bool) -> None:
        has = bool(self.saved)
        self.status.setVisible(has and not editing)
        self.editor.setVisible(editing or not has)
        self.cancel.setVisible(has and editing)
        if not editing:
            self.edit.clear()
        elif has:
            self.edit.setFocus()
        self.hint.setText(f"Nouvelle clé à créer sur {self.console}. Elle remplacera l'ancienne à l'enregistrement."
                          if has and editing else
                          "" if has else
                          f"Créez-la sur {self.console}, puis collez-la ici. Sans clé, TriBin fonctionne mais "
                          "chaque fichier est à ranger à la main.")
        self.hint.setVisible(bool(self.hint.text()))

    def _show(self, on: bool) -> None:
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        self.show_key.setText("Masquer" if on else "Afficher")

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, text: str) -> None:  # noqa: N802 — même nom que QLineEdit
        self.edit.setText(text)


# --- bouton avec raccourci ----------------------------------------------------------------------


class KeyButton(QPushButton):
    """Bouton « Ranger ici  [Entrée] » : libellé et touche de raccourci affichée."""

    def __init__(self, text: str, key: str = "", kind: str = ""):
        super().__init__()
        if kind:
            self.setObjectName(kind)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(8)
        self.label = QLabel(text)
        self.label.setObjectName("BtnText")
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.label)
        if key:
            hint = QLabel(key)
            hint.setObjectName("KbdDark" if kind == "Primary" else "Kbd")
            hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            hint.setFixedHeight(18)
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(38)
        self.setAccessibleName(text)

    def sizeHint(self) -> QSize:  # noqa: N802 — API Qt
        hint = self.layout().sizeHint()
        return QSize(hint.width() + 6, max(38, hint.height()))


# --- barre de confiance ---------------------------------------------------------------------------


class ConfidenceBar(QWidget):
    """Barre fine remplie selon la confiance, dans la couleur de son niveau."""

    def __init__(self, width: int = 160) -> None:
        super().__init__()
        self.value: float | None = None
        self.color = QColor("#14B8A6")
        self.setFixedSize(width, 6)
        self.setAccessibleName("Confiance de l'IA")

    def set_value(self, value: float | None, color: str = "#14B8A6") -> None:
        self.value, self.color = value, QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — API Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ECEEF4"))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 3, 3)
        if self.value is not None:
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(0, 0, max(6.0, self.width() * self.value), self.height()), 3, 3)
        p.end()


# --- fil d'Ariane ---------------------------------------------------------------------------------


class Breadcrumb(QWidget):
    """Destination en texte : Client › Année › Projet › Catégorie (la dernière en gras)."""

    def __init__(self) -> None:
        super().__init__()
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(6)

    def set_parts(self, parts: list[str]) -> None:
        while self.row.count():
            widget = self.row.takeAt(0).widget()
            if widget:
                widget.hide()  # sinon visible jusqu'à sa destruction effective
                widget.deleteLater()
        if not parts:
            empty = QLabel("Aucun dossier choisi")
            empty.setObjectName("Muted")
            self.row.addWidget(empty)
            empty.show()
            return
        for index, part in enumerate(parts):
            if index:
                sep = QLabel("›")
                sep.setObjectName("CrumbSep")
                self.row.addWidget(sep)
                sep.show()
            chip = QLabel(part)
            chip.setObjectName("CrumbActive" if index == len(parts) - 1 else "Crumb")
            self.row.addWidget(chip)
            chip.show()  # ajouté à un widget déjà visible : à afficher explicitement


# --- aperçus de fichiers --------------------------------------------------------------------------


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


def thumbnail(path: Path, width: int, height: int | None = None) -> QPixmap:
    """Miniature d'une image, aperçu d'un PDF/AI/PSD, sinon l'icône du type de fichier."""
    height = height or width
    suffix = path.suffix.lower()
    pix = QPixmap()
    if suffix in IMAGE_EXT and path.exists():
        pix = QPixmap(str(path))
    elif suffix in PREVIEW_EXT and path.exists():
        stat = path.stat()
        data = _preview_bytes(str(path), stat.st_mtime, stat.st_size)
        if data:
            pix.loadFromData(data)
    if not pix.isNull():
        return pix.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    side = min(width, height)
    return QFileIconProvider().icon(QFileInfo(str(path))).pixmap(side, side)
