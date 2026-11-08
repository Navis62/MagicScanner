"""Stop : si du Python a changé pendant ce tour, lance les tests rapides avant de rendre la main.

    tests_on_stop.py snapshot   # UserPromptSubmit : mémorise l'état des .py modifiés au début du tour
    tests_on_stop.py            # Stop : relance pytest seulement si cet état a changé depuis

Un travail en cours de l'utilisateur, déjà modifié avant le tour, ne déclenche donc pas les tests. Sans instantané
(hook ajouté en cours de session), on retombe sur « un .py modifié depuis le dernier commit ».
Un échec renvoie le code 2 : Claude reçoit la fin du rapport et continue pour corriger. `stop_hook_active` évite de
boucler : au second arrêt consécutif, on laisse finir (l'échec a déjà été signalé une fois).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def changed_python(root: Path) -> list[Path]:
    """Fichiers .py de magicscanner/ et tests/ modifiés ou non suivis depuis le dernier commit."""
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "magicscanner", "tests"],
                       check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=root, timeout=30)
    names = (line[3:].split(" -> ")[-1].strip('"') for line in r.stdout.splitlines())
    return [root / n for n in names if n.endswith(".py")]


def fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(changed_python(root)):
        st = p.stat() if p.exists() else None
        h.update(f"{p}|{st.st_mtime_ns if st else 0}|{st.st_size if st else -1}\n".encode())
    return h.hexdigest()


def state_file(data: dict) -> Path:
    session = re.sub(r"[^\w-]", "_", str(data.get("session_id") or "sans-session"))
    return Path(tempfile.gettempdir()) / "magicscanner-hooks" / f"{session}.txt"


def main() -> int:
    sys.stderr.reconfigure(encoding="utf-8")
    data = json.load(sys.stdin.buffer)   # octets UTF-8 : sys.stdin décoderait en cp1252 sous Windows
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".").resolve()
    state = state_file(data)
    try:
        if sys.argv[1:] == ["snapshot"]:
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(fingerprint(root), encoding="utf-8")
            return 0
        if data.get("stop_hook_active"):
            return 0
        if state.exists():
            if state.read_text(encoding="utf-8") == fingerprint(root):
                return 0   # rien de modifié pendant ce tour
        elif not changed_python(root):
            return 0
        r = subprocess.run([sys.executable, "-m", "pytest", "-m", "not integration", "-q", "-x", "--no-header", "-p",
                            "no:cacheprovider"], check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=root, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if r.returncode in (0, 5):   # 5 = aucun test collecté
        return 0
    tail = "\n".join(r.stdout.strip().splitlines()[-30:])
    print(f"Les tests rapides échouent après tes modifications (pytest -m 'not integration') :\n{tail}",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
