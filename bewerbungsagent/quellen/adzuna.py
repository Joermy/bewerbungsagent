"""Adzuna - offizielle Such-API, sammelt Anzeigen vieler Jobboersen und Firmenseiten.

Kostenloser Schluessel: https://developer.adzuna.com (App-ID und App-Key in .env:
ADZUNA_APP_ID, ADZUNA_APP_KEY). Die Beschreibung ist nur ein Auszug; beworben wird
ueber den Link zur Originalanzeige.
"""
from __future__ import annotations

from typing import Iterator

import httpx

from ..stelle import Stelle
from .gemeinsam import QuellenFehler, baue

BASIS = "https://api.adzuna.com/v1/api/jobs/{land}/search/{seite}"
QUELLE = "adzuna"


class Adzuna:
    name = "Adzuna"

    def __init__(self, app_id: str, app_key: str, land: str = "de", client: httpx.Client | None = None):
        if not app_id or not app_key:
            raise QuellenFehler("Adzuna: ADZUNA_APP_ID und ADZUNA_APP_KEY in .env eintragen")
        self.app_id, self.app_key, self.land = app_id, app_key, (land or "de").lower()
        self.client = client or httpx.Client(timeout=30, headers={"User-Agent": "bewerbungsagent"})

    def suche(self, was: str, wo: str, umkreis_km: int = 25, tage: int = 14, max_treffer: int = 40,
              ausbildung: bool = False) -> Iterator[Stelle]:
        geliefert, seite = 0, 1
        while geliefert < max_treffer:
            params = {
                "app_id": self.app_id, "app_key": self.app_key, "what": was, "where": wo,
                "distance": umkreis_km, "max_days_old": tage, "results_per_page": min(50, max_treffer),
                "sort_by": "date", "content-type": "application/json",
            }
            antwort = self.client.get(BASIS.format(land=self.land, seite=seite), params=params)
            if antwort.status_code in (401, 403):
                raise QuellenFehler("Adzuna lehnt den Schluessel ab - App-ID und App-Key pruefen")
            antwort.raise_for_status()
            treffer = antwort.json().get("results") or []
            for t in treffer:
                yield zu_stelle(t)
                geliefert += 1
                if geliefert >= max_treffer:
                    return
            if len(treffer) < params["results_per_page"]:
                return
            seite += 1


def zu_stelle(t: dict) -> Stelle:
    ort = (t.get("location") or {}).get("display_name", "")
    vertrag = t.get("contract_time") or ""
    return baue(
        QUELLE,
        str(t.get("id") or t.get("adref") or ""),
        t.get("title") or "",
        (t.get("company") or {}).get("display_name", ""),
        beschreibung=t.get("description") or "",
        url=t.get("redirect_url") or "",
        ort=ort.split(",")[0],
        veroeffentlicht=t.get("created") or "",
        vollzeit=True if vertrag == "full_time" else False if vertrag == "part_time" else None,
    )
