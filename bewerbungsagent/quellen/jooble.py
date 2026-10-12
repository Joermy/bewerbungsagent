"""Jooble - offizielle REST-API (Schluessel kostenlos unter https://jooble.org/api/about,
in .env als JOOBLE_KEY). Liefert Auszug und Link zur Originalanzeige."""
from __future__ import annotations

import hashlib
from typing import Iterator

import httpx

from ..stelle import Stelle
from .gemeinsam import QuellenFehler, baue

BASIS = "https://jooble.org/api/{key}"
QUELLE = "jooble"


class Jooble:
    name = "Jooble"

    def __init__(self, key: str, client: httpx.Client | None = None):
        if not key:
            raise QuellenFehler("Jooble: JOOBLE_KEY in .env eintragen")
        self.key = key
        self.client = client or httpx.Client(timeout=30, headers={"User-Agent": "bewerbungsagent"})

    def suche(self, was: str, wo: str, umkreis_km: int = 25, tage: int = 14, max_treffer: int = 40,
              ausbildung: bool = False) -> Iterator[Stelle]:
        geliefert, seite = 0, 1
        while geliefert < max_treffer:
            koerper = {"keywords": was, "location": wo, "radius": str(umkreis_km), "page": str(seite)}
            antwort = self.client.post(BASIS.format(key=self.key), json=koerper)
            if antwort.status_code in (401, 403):
                raise QuellenFehler("Jooble lehnt den Schluessel ab")
            antwort.raise_for_status()
            jobs = antwort.json().get("jobs") or []
            for j in jobs:
                yield zu_stelle(j)
                geliefert += 1
                if geliefert >= max_treffer:
                    return
            if not jobs:
                return
            seite += 1


def zu_stelle(j: dict) -> Stelle:
    kennung = str(j.get("id") or hashlib.sha1((j.get("link") or j.get("title", "")).encode()).hexdigest()[:16])
    return baue(
        QUELLE,
        kennung,
        j.get("title") or "",
        j.get("company") or "",
        beschreibung=j.get("snippet") or "",
        url=j.get("link") or "",
        ort=(j.get("location") or "").split(",")[0],
        veroeffentlicht=j.get("updated") or "",
        vollzeit=True if "voll" in (j.get("type") or "").lower() or "full" in (j.get("type") or "").lower()
        else False if "teil" in (j.get("type") or "").lower() or "part" in (j.get("type") or "").lower() else None,
    )
