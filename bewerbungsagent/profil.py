from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Profil:
    name: str
    strasse: str
    plz_ort: str
    telefon: str
    email: str
    wohnort: str
    suchbegriffe: list[str]
    ausschluss: list[str] = field(default_factory=list)
    arbeitszeit: str = "egal"
    schulabschluss: str = ""
    portfolio: str = ""
    arbeitsproben: list[str] = field(default_factory=list)
    text: str = ""

    @property
    def absenderzeilen(self) -> list[str]:
        return [z for z in (self.name, self.strasse, self.plz_ort, self.telefon, self.email) if z]


PFLICHT = ("name", "strasse", "plz_ort", "email", "wohnort", "suchbegriffe")


_KOPF = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.S)


def parse(inhalt: str) -> Profil:
    treffer = _KOPF.match(inhalt)
    if not treffer:
        raise ValueError("Profil braucht YAML-Frontmatter zwischen zwei Zeilen, die nur '---' enthalten.")
    kopf, text = treffer.groups()
    meta = yaml.safe_load(kopf) or {}
    fehlend = [k for k in PFLICHT if not meta.get(k)]
    if fehlend:
        raise ValueError(f"Profil: Pflichtfelder fehlen: {', '.join(fehlend)}")
    return Profil(
        name=str(meta["name"]),
        strasse=str(meta["strasse"]),
        plz_ort=str(meta["plz_ort"]),
        telefon=str(meta.get("telefon") or ""),
        email=str(meta["email"]),
        wohnort=str(meta["wohnort"]),
        suchbegriffe=[str(s) for s in meta["suchbegriffe"]],
        ausschluss=[str(s) for s in meta.get("ausschluss") or []],
        arbeitszeit=str(meta.get("arbeitszeit") or "egal").lower(),
        schulabschluss=str(meta.get("schulabschluss") or "").lower(),
        portfolio=str(meta.get("portfolio") or "").strip(),
        arbeitsproben=[str(u).strip() for u in meta.get("arbeitsproben") or [] if str(u).strip()],
        text=text.strip(),
    )


def lade(pfad: Path) -> Profil:
    if not pfad.exists():
        raise FileNotFoundError(
            f"Profil fehlt: {pfad}. Vorlage: profil.example.md nach profil/profil.md kopieren."
        )
    return parse(pfad.read_text(encoding="utf-8"))
