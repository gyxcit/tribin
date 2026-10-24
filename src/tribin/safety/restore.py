"""Script de restauration AUTONOME : bibliothèque standard Python uniquement (section 7.1).

Il fonctionne même si le reste de l'application est cassé :

    python src/tribin/safety/restore.py --journal <dossier_journal> --list
    python src/tribin/safety/restore.py --journal <dossier_journal> --batch b_...
    python src/tribin/safety/restore.py --journal <dossier_journal> --operation op_...
    python src/tribin/safety/restore.py --journal <dossier_journal> --since 2026-10-15T09:00
    # Ajouter --execute pour agir réellement. Sans ce drapeau : simulation (par défaut).

Ce module contient aussi la lecture et l'écriture du journal : l'application l'utilise pour sa fonction « Annuler ».
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

APP_VERSION = "0.1.0"
CHUNK = 1024 * 1024
PARTIAL_SUFFIX = ".tribin-partial"
RESTORE_SUFFIX = "_restaure"
FILE_ACTIONS = {"stage", "move", "rename", "archive"}
REVERSIBLE = FILE_ACTIONS | {"mkdir"}
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_JOURNAL_LOCK = threading.Lock()  # écritures concurrentes (analyses en arrière-plan)


# --- utilitaires ------------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"


def sha256_file(path: Path) -> str:
    """Hash SHA-256 par blocs de 1 Mo (jamais le fichier entier en mémoire)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def find_existing(path: Path) -> Path | None:
    """Chemin existant désignant le même fichier (insensible à la casse et à la forme Unicode)."""
    path = Path(path)
    if path.exists():
        return path
    if not path.parent.is_dir():
        return None
    target = unicodedata.normalize("NFC", path.name).casefold()
    try:
        for entry in os.scandir(path.parent):
            if unicodedata.normalize("NFC", entry.name).casefold() == target:
                return Path(entry.path)
    except OSError:
        return None
    return None


def free_path(path: Path, suffix: str = "_") -> Path:
    """Premier chemin libre : nom, puis nom<suffix>, nom<suffix>_2…  (jamais d'écrasement)."""
    path = Path(path)
    if find_existing(path) is None:
        return path
    name = path.name
    lower = name.lower()
    ext = ""
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if lower.endswith(compound):
            ext = name[-len(compound):]
            break
    if not ext and "." in name[1:]:
        ext = name[name.rfind("."):]
    stem = name[: len(name) - len(ext)] if ext else name
    base = stem + suffix if suffix != "_" else stem
    candidates = [base] if suffix != "_" else []
    candidates += [f"{base}_{i}" for i in range(2, 10000)]
    for cand in candidates:
        candidate = path.with_name(cand + ext)
        if find_existing(candidate) is None:
            return candidate
    raise FileExistsError(f"Aucun nom libre pour {path}")


def same_volume(a: Path, b: Path) -> bool:
    def device(p: Path) -> int:
        p = Path(p)
        while not p.exists() and p != p.parent:
            p = p.parent
        return os.stat(p).st_dev

    return device(a) == device(b)


def safe_move(src: Path, dst: Path, after_copy=None) -> tuple[str | None, str | None]:
    """Déplace sans jamais écraser. Renvoie (hash_avant, hash_après) pour une copie inter-volumes.

    Inter-volumes : copie vers <nom>.tribin-partial, vérification SHA-256, renommage, puis retrait de l'original.
    En cas d'échec : l'original reste intact et le fichier partiel est retiré.
    """
    src, dst = Path(src), Path(dst)
    if find_existing(dst) is not None:
        raise FileExistsError(f"La destination existe déjà : {dst}")
    size = src.stat().st_size
    if same_volume(src, dst.parent):
        os.rename(src, dst)  # existence vérifiée juste avant (os.rename écrase sous macOS)
        if not dst.exists() or dst.stat().st_size != size:
            raise OSError(f"Vérification après déplacement impossible : {dst}")
        return None, None
    partial = dst.with_name(dst.name + PARTIAL_SUFFIX)
    if find_existing(partial) is not None:
        raise FileExistsError(f"Un fichier partiel existe déjà : {partial}")
    try:
        hash_before = sha256_file(src)
        with open(src, "rb") as fin, open(partial, "xb") as fout:
            for block in iter(lambda: fin.read(CHUNK), b""):
                fout.write(block)
            fout.flush()
            os.fsync(fout.fileno())
        if after_copy:
            after_copy(partial)
        hash_after = sha256_file(partial)
        if hash_after != hash_before:
            raise OSError("La copie ne correspond pas à l'original (hash différent).")
        if find_existing(dst) is not None:
            raise FileExistsError(f"La destination existe déjà : {dst}")
        os.rename(partial, dst)
    except BaseException:
        if partial.exists():
            os.remove(partial)  # seul le fichier partiel est retiré ; l'original est intact
        raise
    try:
        import shutil

        shutil.copystat(src, dst)
    except OSError:
        pass
    os.remove(src)  # exception autorisée : copie inter-volumes vérifiée
    return hash_before, hash_after


# --- journal ----------------------------------------------------------------------------------


def journal_file(journal_dir: Path, when: datetime | None = None) -> Path:
    when = when or datetime.now()
    return Path(journal_dir) / f"journal-{when:%Y-%m}.jsonl"


def append_record(journal_dir: Path, record: dict) -> dict:
    """Ajoute une ligne au journal (ajout seulement), puis flush() et fsync()."""
    Path(journal_dir).mkdir(parents=True, exist_ok=True)
    record = {"ts": now_iso(), **record}
    record.setdefault("app_version", APP_VERSION)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _JOURNAL_LOCK, open(journal_file(journal_dir), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return record


def read_records(journal_dir: Path) -> list[dict]:
    """Toutes les lignes du journal, dans l'ordre. Une ligne abîmée (plantage pendant l'écriture) est ignorée."""
    records: list[dict] = []
    for path in sorted(Path(journal_dir).glob("journal-*.jsonl")):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def latest_states(records: list[dict]) -> dict[str, dict]:
    """État de chaque opération : sa dernière ligne."""
    states: dict[str, dict] = {}
    for record in records:
        if record.get("operation_id"):
            states[record["operation_id"]] = record
    return states


def select_operations(states: dict[str, dict], batch: str | None = None, operation: str | None = None,
                      since: str | None = None) -> list[dict]:
    """Opérations « done » réversibles à annuler, de la plus récente à la plus ancienne."""
    chosen = []
    for op in states.values():
        if op.get("status") != "done" or op.get("action") not in REVERSIBLE:
            continue
        if batch and op.get("batch_id") != batch:
            continue
        if operation and op.get("operation_id") != operation:
            continue
        if since and not _after(op.get("ts", ""), since):
            continue
        chosen.append(op)
    chosen.sort(key=lambda o: (o.get("ts", ""), o.get("operation_id", "")), reverse=True)
    return chosen


def _after(ts: str, since: str) -> bool:
    try:
        a = datetime.fromisoformat(ts)
        b = datetime.fromisoformat(since)
        if b.tzinfo is None and a.tzinfo is not None:
            b = b.replace(tzinfo=a.tzinfo)
        return a >= b
    except ValueError:
        return False


# --- annulation -------------------------------------------------------------------------------


def check_undo(op: dict) -> tuple[str | None, Path | None]:
    """Vérifie qu'une opération peut être annulée. Renvoie (problème, chemin de retour)."""
    action = op.get("action")
    dest = Path(op["destination"]) if op.get("destination") else None
    if dest is None:
        return "destination inconnue dans le journal", None
    if action == "mkdir":
        if op.get("already_existed"):
            return "dossier déjà existant avant l'opération : conservé", None
        if not dest.is_dir():
            return "dossier introuvable", None
        if any(dest.iterdir()):
            return "dossier non vide : conservé", None
        return None, dest
    current = find_existing(dest)
    if current is None or not current.is_file():
        return f"fichier absent de sa destination ({dest}) : il a été déplacé entre-temps", None
    if op.get("size") is not None and current.stat().st_size != op["size"]:
        return "taille différente : le fichier a été modifié depuis", None
    expected_hash = op.get("hash_after") or op.get("hash_before")
    if expected_hash and sha256_file(current) != expected_hash:
        return "contenu différent (hash) : le fichier a été modifié depuis", None
    source = Path(op["source"])
    target = source if find_existing(source) is None else free_path(source, RESTORE_SUFFIX)
    return None, target


def undo_one(op: dict, journal_dir: Path, execute: bool, user: str, guard=None) -> dict:
    """Annule une opération (ou la simule). Renvoie un résultat lisible."""
    problem, target = check_undo(op)
    result = {"operation_id": op["operation_id"], "action": op.get("action"), "from": op.get("destination"),
              "to": str(target) if target else None, "status": "would_undo" if not execute else "pending",
              "message": problem or ""}
    if problem:
        result["status"] = "ignored"
        return result
    if guard:
        try:
            guard(Path(op["destination"]))
            guard(target)
        except Exception as exc:
            result.update(status="ignored", message=str(exc))
            return result
    if not execute:
        return result
    undo_id = new_id("op")
    base = {"operation_id": undo_id, "batch_id": op.get("batch_id"), "user": user, "action": "undo",
            "undoes": op["operation_id"], "undone_action": op.get("action"), "source": op.get("destination"),
            "destination": str(target), "size": op.get("size")}
    append_record(journal_dir, {**base, "status": "pending"})
    try:
        if op.get("action") == "mkdir":
            os.rmdir(target)  # ne retire qu'un dossier vide
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            safe_move(find_existing(Path(op["destination"])), target)
    except Exception as exc:
        message = _error_message(exc)
        append_record(journal_dir, {**base, "status": "failed", "error": message})
        result.update(status="failed", message=message)
        return result
    append_record(journal_dir, {**base, "status": "done"})
    append_record(journal_dir, {**op, "ts": now_iso(), "status": "undone", "undone_by": undo_id})
    result["status"] = "undone"
    if target and Path(op.get("source", "")) != target and op.get("action") != "mkdir":
        result["message"] = f"emplacement d'origine occupé : restauré sous {target.name}"
    return result


def _error_message(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "Fichier ouvert dans une autre application : ferme-le puis réessaie."
    return f"{type(exc).__name__}: {exc}"


def undo(journal_dir: Path, batch: str | None = None, operation: str | None = None, since: str | None = None,
         execute: bool = False, user: str | None = None, guard=None) -> list[dict]:
    """Annule (ou simule l'annulation de) la sélection, dans l'ordre chronologique inverse."""
    user = user or _user()
    ops = select_operations(latest_states(read_records(journal_dir)), batch, operation, since)
    return [undo_one(op, journal_dir, execute, user, guard) for op in ops]


def _user() -> str:
    try:
        return os.environ.get("TRIBIN_USER") or getpass.getuser()
    except Exception:
        return "utilisateur"


# --- ligne de commande ------------------------------------------------------------------------


def _print_list(journal_dir: Path) -> None:
    states = latest_states(read_records(journal_dir))
    batches: dict[str, list[dict]] = {}
    for op in states.values():
        batches.setdefault(op.get("batch_id") or "(sans lot)", []).append(op)
    for batch_id, ops in sorted(batches.items(), key=lambda kv: min(o.get("ts", "") for o in kv[1])):
        print(f"\nLot {batch_id}")
        for op in sorted(ops, key=lambda o: o.get("ts", "")):
            print(f"  {op.get('ts', '')[:19]}  {op['operation_id']}  {op.get('action', ''):8} {op.get('status', ''):9} "
                  f"{op.get('source') or ''} -> {op.get('destination') or ''}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Restauration TriBin à partir du journal des opérations.")
    parser.add_argument("--journal", type=Path, required=True, help="dossier contenant journal-AAAA-MM.jsonl")
    parser.add_argument("--list", action="store_true", help="lister les opérations")
    parser.add_argument("--batch")
    parser.add_argument("--operation")
    parser.add_argument("--since", help="ex. 2026-10-15T09:00")
    parser.add_argument("--execute", action="store_true", help="agir réellement (sinon : simulation)")
    args = parser.parse_args(argv)
    if not args.journal.is_dir():
        print(f"Dossier de journal introuvable : {args.journal}")
        return 1
    if args.list:
        _print_list(args.journal)
        return 0
    if not (args.batch or args.operation or args.since):
        print("Précise --batch, --operation ou --since (ou --list).")
        return 1
    results = undo(args.journal, args.batch, args.operation, args.since, execute=args.execute)
    if not results:
        print("Aucune opération à annuler pour cette sélection.")
    for r in results:
        print(f"[{r['status']}] {r['operation_id']} {r['action']} : {r['from']} -> {r['to'] or '-'} {r['message']}")
    if not args.execute:
        print("\nSimulation uniquement : ajoute --execute pour restaurer réellement.")
    return 0 if all(r["status"] in {"undone", "would_undo"} for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
