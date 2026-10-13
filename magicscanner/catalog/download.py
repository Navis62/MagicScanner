"""Téléchargement en flux vers un fichier (écriture atomique via .part)."""
import logging
from pathlib import Path

import httpx

from ..config import SCRYFALL_HEADERS

log = logging.getLogger(__name__)


def download(url: str, dest: Path) -> Path:
    log.info("téléchargement %s", url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, headers=SCRYFALL_HEADERS, follow_redirects=True, timeout=None) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            f.writelines(r.iter_bytes(1 << 20))
    tmp.replace(dest)
    return dest
