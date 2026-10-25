"""Activité tirée du journal : les rangements (un par fichier) et les statistiques de l'Accueil."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from tribin.safety.journal import Journal

DECISIONS = {
    "accepted": "Proposition de l'IA acceptée telle quelle",
    "auto": "Rangé automatiquement (IA sûre d'elle)",
    "edited": "Corrigé par vous",
    "alternative_chosen": "Autre piste de l'IA choisie par vous",
    "reorganisation": "Réorganisation de dossiers",
}
CORRECTED = {"edited", "alternative_chosen"}


@dataclass
class Placement:
    """Un fichier rangé (ou dont le rangement a été annulé ou a échoué)."""

    operation_id: str
    batch_id: str
    when: datetime
    name: str  # nom à destination
    original_name: str
    destination: Path
    source: Path | None
    folder: str  # dossier de destination, relatif à la racine
    category: str
    confidence: float | None
    decision: str
    status: str  # done · undone · failed
    ai_folder: str = ""
    error: str = ""

    @property
    def decision_label(self) -> str:
        return DECISIONS.get(self.decision, "Rangé")

    @property
    def current_path(self) -> Path | None:
        """Là où le fichier se trouve maintenant (à destination, ou revenu après une annulation)."""
        return self.source if self.status == "undone" else self.destination


def _when(op: dict) -> datetime:
    try:
        return datetime.fromisoformat((op.get("ts") or "")[:19])
    except ValueError:
        return datetime.min


def _category(folder: str) -> str:
    """Catégorie = dernier niveau du dossier, ou l'avant-dernier si c'est une année (« Sante/2026 »)."""
    parts = [p for p in folder.split("/") if p]
    if len(parts) >= 2 and parts[-1].isdigit() and len(parts[-1]) == 4:
        return parts[-2]
    return parts[-1] if parts else ""


def placements(journal: Journal, since: date | None = None) -> list[Placement]:
    """Rangements de fichiers, du plus récent au plus ancien (hors anciennes versions mises de côté)."""
    result = []
    for op in journal.operations():
        if op.get("action") != "move" or op.get("version_archive") or op.get("status") not in {"done", "undone", "failed"}:
            continue
        when = _when(op)
        if since and when.date() < since:
            continue
        destination = Path(op.get("destination") or "")
        root = Path(op["root"]) if op.get("root") else None
        try:
            folder = destination.parent.relative_to(root).as_posix() if root else destination.parent.as_posix()
        except ValueError:
            folder = destination.parent.as_posix()
        source = Path(op["source"]) if op.get("source") else None
        ai = op.get("ai_proposal") or {}
        result.append(Placement(
            operation_id=op["operation_id"], batch_id=op.get("batch_id") or op["operation_id"], when=when,
            name=destination.name, original_name=source.name if source else destination.name,
            destination=destination, source=source, folder=folder, category=_category(folder),
            confidence=ai.get("confidence"), decision=op.get("decision") or "", status=op.get("status", ""),
            ai_folder=ai.get("target_folder") or "", error=op.get("error") or ""))
    result.sort(key=lambda p: p.when, reverse=True)
    return result


@dataclass
class Stats:
    filed: int = 0  # fichiers rangés (et pas annulés)
    this_month: int = 0
    accepted: int = 0  # proposition acceptée telle quelle
    auto: int = 0  # rangés sans aucun clic
    corrected: int = 0  # retours humains : dossier ou nom corrigé
    undone: int = 0

    @property
    def reviewed(self) -> int:
        return self.accepted + self.auto + self.corrected

    @property
    def without_correction(self) -> float | None:
        """Part des fichiers rangés sans correction humaine (l'efficacité de l'IA)."""
        return (self.accepted + self.auto) / self.reviewed if self.reviewed else None


def compute_stats(items: list[Placement], today: date | None = None) -> Stats:
    today = today or date.today()
    stats = Stats()
    for p in items:
        if p.decision == "reorganisation":
            continue  # déplacements de dossiers, pas des propositions de l'IA
        if p.status == "undone":
            stats.undone += 1
            continue
        if p.status != "done":
            continue
        stats.filed += 1
        if (p.when.year, p.when.month) == (today.year, today.month):
            stats.this_month += 1
        if p.decision == "accepted":
            stats.accepted += 1
        elif p.decision == "auto":
            stats.auto += 1
        elif p.decision in CORRECTED:
            stats.corrected += 1
    return stats
