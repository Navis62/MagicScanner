"""Passe une ou plusieurs photos dans la reconnaissance et affiche ce qu'elle a vu et décidé.

    python .claude/skills/diagnose-scan/scripts/diagnose.py tests/fixtures/*.jpg
    python .claude/skills/diagnose-scan/scripts/diagnose.py failed            # data/scans/failed/
    python .claude/skills/diagnose-scan/scripts/diagnose.py img.jpg --orientation landscape --locked-set c13 --foil
    ... --save DOSSIER   # écrit la carte redressée vue par l'OCR

Lecture seule : la base est ouverte en `mode=ro`, sans créer de table ni migrer (une migration en cours d'écriture
ne doit pas être appliquée au stock réel par un simple diagnostic).
"""
import argparse
import glob
import logging
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import cv2

from magicscanner.config import DB_PATH, SCANS_DIR


def expand(args: list[str]) -> list[Path]:
    paths = []
    for a in args:
        if a == "failed":
            paths += sorted((SCANS_DIR / "failed").glob("*.jpg"))
        else:
            paths += [Path(p) for p in (glob.glob(a) or [a])]
    return paths


def describe(con, card_id: str) -> str:
    r = con.execute("SELECT name, set_code, collector_number, rarity FROM cards WHERE id=?", (card_id,)).fetchone()
    return f"{r['name']} [{r['set_code'].upper()} {r['collector_number']}, {r['rarity']}]" if r else card_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+", help="fichiers, motifs glob, ou « failed »")
    ap.add_argument("--orientation", choices=["portrait", "landscape"])
    ap.add_argument("--locked-set")
    ap.add_argument("--foil", action="store_true")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--save", type=Path, help="dossier où écrire la carte redressée")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # console Windows en cp1252
    logging.disable(logging.WARNING)                              # RapidOCR est bavard au chargement

    if not DB_PATH.exists():
        print(f"Base absente ({DB_PATH}) : lancer `magicscanner import` d'abord.")
        return 1
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer

    con = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    locked_set = args.locked_set.lower() if args.locked_set else None   # codes en minuscules dans la base
    t = time.perf_counter()
    rec = Recognizer(Catalog(con))
    print(f"(initialisation {time.perf_counter() - t:.1f} s)\n")

    failures = 0
    for path in expand(args.images):
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"== {path} : illisible\n")
            failures += 1
            continue
        t = time.perf_counter()
        r = rec.recognize(frame, foil=args.foil, locked_set=locked_set, orientation=args.orientation)
        dt = time.perf_counter() - t
        flags = [f for f, on in (("AMBIGU", r.ambiguous), ("HORS-ÉDITION", r.off_set)) if on]
        print(f"== {path.name}  ({dt:.2f} s)  {'OK' if r.ok else 'ÉCHEC: ' + str(r.error)}  {' '.join(flags)}")
        print(f"   titre lu : {r.title!r}  langue={r.lang}  nom={r.name_score:.0f}  confiance={r.confidence:.2f}"
              f"  étincelle={r.list_symbol:.2f}")
        if r.lines:
            print(f"   lignes OCR : {r.lines[:8]}")
        for i, c in enumerate(r.candidates[:args.top], 1):
            print(f"   {i}. {c.score:+.3f} (visuel {c.visual:.3f})  {describe(con, c.card_id)}"
                  f"  cm={c.cardmarket_id}  {', '.join(c.reasons)}")
        if args.save and r.warped is not None:
            args.save.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(args.save / f"{path.stem}_warped.jpg"), r.warped)
        failures += not r.ok
        print()
    con.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
