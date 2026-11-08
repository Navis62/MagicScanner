"""PostToolUse (Edit, Write) : `ruff check` sur le fichier Python qui vient d'être modifié.

En cas d'erreur, code 2 : le rapport (stderr) est montré à Claude, qui corrige tout de suite au lieu de le découvrir
au commit. Pas de `ruff format` : le style du dépôt est voulu.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    sys.stderr.reconfigure(encoding="utf-8")
    data = json.load(sys.stdin.buffer)   # octets UTF-8 : sys.stdin décoderait en cp1252 sous Windows
    path = data.get("tool_input", {}).get("file_path", "")
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".").resolve()
    if not path.endswith(".py") or not Path(path).exists() or not Path(path).resolve().is_relative_to(root):
        return 0   # seuls les fichiers Python du dépôt sont concernés
    try:
        r = subprocess.run([sys.executable, "-m", "ruff", "check", "--quiet", "--output-format", "concise", path],
                           check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, cwd=root)
    except (OSError, subprocess.TimeoutExpired):
        return 0   # ruff absent ou bloqué : ne pas gêner le travail
    if r.returncode == 0 or "No module named ruff" in r.stderr:
        return 0
    report = "\n".join(s for s in (r.stdout.strip(), r.stderr.strip()) if s)   # stderr : configuration invalide…
    print(f"ruff signale des problèmes dans {path} :\n{report}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
