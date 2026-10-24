"""Journal des opérations (JSON Lines, ajout seulement — section 7).

L'implémentation de bas niveau vit dans restore.py (bibliothèque standard uniquement) pour que le script
de restauration reste autonome ; ce module l'expose à l'application.
"""

from __future__ import annotations

from pathlib import Path

from tribin.safety.restore import append_record, latest_states, read_records

STATUSES = {"simulated", "pending", "done", "failed", "skipped", "undone"}
ACTIONS = {"stage", "mkdir", "move", "rename", "archive", "undo"}


class Journal:
    """Accès au journal d'un dossier (un fichier par mois)."""

    def __init__(self, journal_dir: Path):
        self.dir = Path(journal_dir)

    def write(self, record: dict) -> dict:
        if record.get("status") not in STATUSES or record.get("action") not in ACTIONS:
            raise ValueError(f"Ligne de journal invalide : {record.get('action')} / {record.get('status')}")
        return append_record(self.dir, record)

    def records(self) -> list[dict]:
        return read_records(self.dir)

    def states(self) -> dict[str, dict]:
        return latest_states(self.records())

    def operations(self, batch_id: str | None = None, include_simulated: bool = False) -> list[dict]:
        """Dernier état de chaque opération, du plus récent au plus ancien."""
        ops = [op for op in self.states().values()
               if (include_simulated or op.get("status") != "simulated") and (not batch_id or op.get("batch_id") == batch_id)]
        ops.sort(key=lambda o: o.get("ts", ""), reverse=True)
        return ops

    def acceptance_rate(self) -> float | None:
        """Taux de propositions acceptées sans modification (indicateur principal en usage réel)."""
        decisions = [op.get("decision") for op in self.states().values()
                     if op.get("action") == "move" and op.get("status") in {"done", "undone"} and op.get("decision")]
        if not decisions:
            return None
        return sum(d == "accepted" for d in decisions) / len(decisions)
