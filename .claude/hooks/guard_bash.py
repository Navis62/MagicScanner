"""PreToolUse (Bash, PowerShell) : bloque les commandes qui détruiraient l'état de l'utilisateur ou l'historique git.

Code de sortie 2 = commande refusée, la raison (stderr) est renvoyée à Claude. Bibliothèque standard uniquement.
Une règle est une liste de motifs qui doivent tous apparaître dans la commande (pas forcément dans le même segment :
`cd data && rm -rf *` est une suppression dans data/).
"""
import json
import re
import sys

# Suppression : commandes shell, PowerShell et appels Python équivalents.
_DELETE = r"\b(rm|del|rmdir|Remove-Item|ri|erase|rd|rmtree|unlink|os\.remove|send2trash)\b"
# Exécution de SQL (et non simple mention dans un grep, un git log ou un message de commit).
_RUN_SQL = r"\b(sqlite3|python3?|py)\b[^|;&]*"

RULES = [
    ([r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b|\s\+\S)"], "push forcé interdit : réécrit l'historique distant"),
    ([r"\bgit\s+.*--no-verify\b"], "--no-verify interdit : corrige la cause au lieu de contourner les vérifications"),
    ([r"\bgit\s+reset\s+--hard\b"], "git reset --hard interdit : du travail non commité serait perdu"),
    ([r"\bgit\s+clean\b[^|;&]*(\s-\w*f|\s--force\b)"],
     "git clean -f interdit : supprimerait des fichiers non suivis (dont data/)"),
    ([r"\bgit\s+checkout\b[^|;&]*\s(--\s+)?(\.|:/)(\s|$)"], "git checkout . interdit : annulerait toutes les modifications en cours"),
    ([r"\bgit\s+checkout\b[^|;&]*\s(-f|--force)\b"], "git checkout -f interdit : annulerait les modifications en cours"),
    ([r"\bgit\s+restore\b(?![^|;&]*--staged(?![^|;&]*(--worktree|\s-W\b)))[^|;&]*\s(\.|:/|\*)(\s|$)"],
     "git restore . interdit : annulerait toutes les modifications en cours"),
    ([r"\bgit\s+stash\s+(drop|clear)\b"], "git stash drop/clear interdit : le travail mis de côté serait perdu"),
    # data/ : base de stock, profil Chrome connecté à Cardmarket, caches de plusieurs centaines de Mo.
    ([_DELETE, r"(\bdata\b|MS_DATA|DATA_DIR)"], "suppression dans data/ interdite : c'est le stock réel"),
    ([r"\b(mv|move|Move-Item|ren|Rename-Item)\b[^|;&]*magicscanner[^ ]*\.db\b"], "déplacement de la base interdit : copie-la plutôt"),
    ([r">\s*\S*data[/\\]magicscanner[^ ]*\.db\b"], "écrasement de la base interdit"),
    ([_RUN_SQL + r"\b(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|UPDATE\s+\w+\s+SET)\b"],
     "requête destructive sur la base réelle interdite"),
    ([r"(data[/\\]+chrome-profile|chrome-profile[/\\])"], "data/chrome-profile contient la session Cardmarket : ne pas y toucher"),
]


def blocked(command: str) -> str | None:
    """Raison du refus de la commande, ou None si elle est admise."""
    for patterns, reason in RULES:
        if all(re.search(p, command, re.IGNORECASE) for p in patterns):
            return reason
    return None


def main() -> int:
    sys.stderr.reconfigure(encoding="utf-8")
    data = json.load(sys.stdin.buffer)   # octets UTF-8 : sys.stdin décoderait en cp1252 sous Windows
    reason = blocked(data.get("tool_input", {}).get("command", ""))
    if reason:
        print(f"Bloqué par .claude/hooks/guard_bash.py : {reason}. Demande à l'utilisateur s'il le faut vraiment.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
