"""Pipeline de reconnaissance : détection -> OCR (RapidOCR) -> nom (recherche floue VO/VF) ->
choix de l'impression (visuel + numéro de collection + code d'édition + cohérence de langue)."""
import re
import sqlite3
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import cv2
import numpy as np
from rapidfuzz import fuzz, process
from rapidocr import RapidOCR

from . import detect, matcher
from .detect import CARD_H, CARD_W

FR_WORDS = {"le", "la", "les", "de", "des", "du", "vous", "une", "un", "et", "chaque", "cible", "carte", "créature",
            "éphémère", "rituel", "terrain", "enchantement", "artefact", "jusqu'à", "contrôlez", "champ", "bataille"}
EN_WORDS = {"the", "you", "of", "a", "an", "and", "each", "target", "card", "creature", "instant", "sorcery", "land",
            "enchantment", "artifact", "until", "control", "battlefield", "your", "when", "draw"}
PROMO_SETS_PREFIX = ("p",)
RARE_PENALTY_SETS = {"plst", "sld", "prm", "mb2", "fmb1"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@dataclass
class OcrLine:
    text: str
    score: float
    x: float  # coin haut-gauche, fraction de la carte
    y: float


@dataclass
class Recognition:
    ok: bool
    error: str | None = None
    lang: str | None = None
    confidence: float = 0.0
    title: str | None = None
    lines: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)  # triées, la première = choix retenu
    warped: np.ndarray | None = None
    corners: list | None = None


class Recognizer:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.ocr = RapidOCR()
        self.pool = ThreadPoolExecutor(8)
        rows = con.execute("SELECT oracle_id, lang, name FROM names").fetchall()
        self.names = [_norm(r["name"]) for r in rows]
        self.name_meta = [(r["oracle_id"], r["lang"], r["name"]) for r in rows]
        self.fr_sets = {r[0] for r in con.execute("SELECT DISTINCT set_code FROM localized WHERE lang='fr'")}
        self.last_set: str | None = None

    # --- OCR -----------------------------------------------------------------------------------------------
    def _read(self, card: np.ndarray) -> list[OcrLine]:
        res = self.ocr(card)
        if res.txts is None:
            return []
        return [OcrLine(t, float(s), float(b[0][0]) / CARD_W, float(b[0][1]) / CARD_H)
                for b, t, s in zip(res.boxes, res.txts, res.scores)]

    def _title_candidates(self, lines: list[OcrLine]) -> list[str]:
        top = sorted((l for l in lines if l.y < 0.13 and l.x < 0.6 and len(l.text) >= 3), key=lambda l: (l.y, l.x))
        return [l.text for l in top[:3]]

    @staticmethod
    def _detect_lang(lines: list[OcrLine]) -> tuple[str | None, float]:
        words = re.findall(r"[a-zA-Zàâçéèêëîïôûùüÿœ']+", " ".join(l.text for l in lines).lower())
        fr = sum(w in FR_WORDS for w in words) + 2 * sum(any(c in w for c in "éèêàçû") for w in words)
        en = sum(w in EN_WORDS for w in words)
        if fr + en < 2:
            return None, 0.0
        return ("fr" if fr > en else "en"), abs(fr - en) / (fr + en)

    @staticmethod
    def _collector_info(lines: list[OcrLine]) -> dict:
        bottom = [l.text for l in lines if l.y > 0.88]
        info: dict = {}
        for t in bottom:
            if m := re.search(r"(\d{1,4})\s*/\s*(\d{2,4})", t):
                info.setdefault("number", m.group(1).lstrip("0") or "0")
                info.setdefault("total", m.group(2).lstrip("0"))
            # Cadre récent : « 0087 U » puis « C13 • FR ».
            if m := re.search(r"\b([A-Z0-9]{3,5})\s*[•·.*\-]\s*(EN|FR)\b", t.upper()):
                info.setdefault("set_code", m.group(1).lower())
            if "number" not in info and (m := re.match(r"^\s*(\d{3,4})\s*[CURMLST]?\s*$", t)):
                info["number"] = m.group(1).lstrip("0") or "0"
        return info

    # --- Nom -> oracle ---------------------------------------------------------------------------------------
    def _match_name(self, titles: list[str]) -> list[tuple[str, str, str, float]]:
        """[(oracle_id, lang_du_nom, nom, score)] triés."""
        found: dict[str, tuple] = {}
        for t in titles:
            for _, score, idx in process.extract(_norm(t), self.names, scorer=fuzz.ratio, limit=8):
                oid, lang, name = self.name_meta[idx]
                if score >= 70 and (oid not in found or score > found[oid][3]):
                    found[oid] = (oid, lang, name, score)
        return sorted(found.values(), key=lambda x: -x[3])

    # --- Impression -----------------------------------------------------------------------------------------
    def _printings(self, oracle_ids: list[str]) -> list[sqlite3.Row]:
        q = ",".join("?" * len(oracle_ids))
        return self.con.execute(
            f"""SELECT c.*, s.name AS set_name, s.icon_svg, COALESCE(s.printed_size, s.card_count) AS set_size,
                       l.printed_name AS fr_name, l.image_normal AS fr_image
                FROM cards c JOIN sets s ON s.code = c.set_code
                LEFT JOIN localized l ON l.set_code = c.set_code AND l.collector_number = c.collector_number AND l.lang = 'fr'
                WHERE c.oracle_id IN ({q})""",
            oracle_ids,
        ).fetchall()

    def _score_printing(self, scan: np.ndarray, p: sqlite3.Row, lang: str | None, coll: dict, name_score: float) -> dict:
        urls = [u for u in ((p["fr_image"] if lang == "fr" else None), p["image_normal"]) if u]
        vis = {"score": 0.0, "symbol": 0.0, "global": 0.0}
        for u in urls[:2]:
            ref = matcher.fetch_image(u)
            if ref is not None:
                s = matcher.similarity(scan, ref)
                if s["score"] > vis["score"]:
                    vis = s
        score = 0.45 * vis["global"] + 0.45 * vis["symbol"] + 0.10 * vis.get("color", 0.0)
        reasons = []
        if coll.get("set_code") == p["set_code"]:
            score += 0.5
            reasons.append("code édition lu")
        if "number" in coll:
            printed = f"{coll['number']}/{coll.get('total', '')}"
            mine = f"{p['collector_number'].lstrip('0')}/{p['set_size'] or ''}"
            score += 0.25 * fuzz.ratio(printed, mine) / 100
            if coll["number"] == p["collector_number"].lstrip("0"):
                score += 0.15
                reasons.append("numéro lu")
        if lang == "fr" and p["set_code"] not in self.fr_sets:
            score -= 0.15  # édition jamais imprimée en français (Scryfall)
        if p["rarity"] in ("common", "uncommon"):
            score += 0.03
        if p["promo"] or p["set_code"] in RARE_PENALTY_SETS or p["set_type"] == "promo":
            score -= 0.08
        if self.last_set and p["set_code"] == self.last_set:
            score += 0.05
        score += 0.2 * (name_score / 100 - 1)
        return {"card_id": p["id"], "score": round(score, 4), "visual": round(vis["score"], 3),
                "symbol": round(vis["symbol"], 3), "reasons": reasons}

    def recognize(self, frame: np.ndarray) -> Recognition:
        card, corners = detect.extract(frame)
        if card is None:
            return Recognition(False, "Carte non détectée : vérifie le cadrage / l'éclairage")
        lines = self._read(card)
        # Carte posée à l'envers : on retourne et on relit si aucun titre plausible.
        titles = self._title_candidates(lines)
        matches = self._match_name(titles) if titles else []
        if not matches:
            flipped = cv2.rotate(card, cv2.ROTATE_180)
            lines2 = self._read(flipped)
            titles2 = self._title_candidates(lines2)
            m2 = self._match_name(titles2) if titles2 else []
            if m2:
                card, lines, titles, matches = flipped, lines2, titles2, m2
        rec = Recognition(False, warped=card, corners=corners.tolist(), lines=[l.text for l in lines],
                          title=titles[0] if titles else None)
        if not matches:
            rec.error = "Nom illisible" if not titles else f"Aucune carte ne correspond à « {titles[0]} »"
            return rec

        lang, lang_conf = self._detect_lang(lines)
        if lang is None:
            lang = matches[0][1]
        rec.lang = lang
        best_name_score = matches[0][3]
        # Garde les noms quasi ex-aequo (ex. OCR hésitant entre deux noms proches).
        oracle_ids = [m[0] for m in matches if m[3] >= best_name_score - 5][:3]
        name_scores = {m[0]: m[3] for m in matches}
        printings = self._printings(oracle_ids)
        coll = self._collector_info(lines)
        scored = list(self.pool.map(
            lambda p: self._score_printing(card, p, lang, coll, name_scores.get(p["oracle_id"], 0)), printings))
        scored.sort(key=lambda s: -s["score"])
        rec.candidates = scored
        rec.ok = bool(scored)
        if scored:
            gap = scored[0]["score"] - (scored[1]["score"] if len(scored) > 1 else 0)
            rec.confidence = round(min(1.0, (best_name_score / 100) * (0.5 + 2 * gap)), 3)
        return rec
