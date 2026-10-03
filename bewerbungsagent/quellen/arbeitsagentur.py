from __future__ import annotations

import base64
import html
import re
import time
from typing import Iterator

import httpx

from ..stelle import Stelle
from .. import kontakt

BASIS = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
KOPF = {"X-API-Key": "jobboerse-jobsuche", "User-Agent": "bewerbungsagent/0.1"}
DETAIL_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"

QUELLE = "ba"

ARBEIT = 1
AUSBILDUNG = 4
ANGEBOTSARTEN = {"arbeit": (ARBEIT,), "ausbildung": (AUSBILDUNG,), "beides": (AUSBILDUNG, ARBEIT)}


class Arbeitsagentur:
    def __init__(self, client: httpx.Client | None = None, pause_s: float = 0.3):
        self.client = client or httpx.Client(timeout=30)
        self.pause_s = pause_s

    def suche(
        self,
        was: str,
        wo: str,
        umkreis_km: int = 25,
        veroeffentlicht_seit_tage: int = 14,
        ohne_zeitarbeit: bool = True,
        max_treffer: int = 50,
        angebotsart: int = ARBEIT,
    ) -> Iterator[dict]:
        params = {
            "was": was,
            "wo": wo,
            "umkreis": umkreis_km,
            "angebotsart": angebotsart,
            "veroeffentlichtseit": veroeffentlicht_seit_tage,
            "size": min(max_treffer, 50),
            "page": 1,
        }
        if ohne_zeitarbeit:
            params["zeitarbeit"] = "false"
        geliefert = 0
        while geliefert < max_treffer:
            antwort = self.client.get(f"{BASIS}/pc/v6/jobs", params=params, headers=KOPF)
            antwort.raise_for_status()
            daten = antwort.json()
            zeilen = daten.get("ergebnisliste") or []
            for zeile in zeilen:
                yield zeile
                geliefert += 1
                if geliefert >= max_treffer:
                    return
            if len(zeilen) < params["size"] or geliefert >= int(daten.get("maxErgebnisse") or 0):
                return
            params["page"] += 1
            time.sleep(self.pause_s)

    def details(self, refnr: str) -> dict:
        kennung = base64.b64encode(refnr.encode()).decode()
        antwort = self.client.get(f"{BASIS}/pc/v4/jobdetails/{kennung}", headers=KOPF)
        antwort.raise_for_status()
        time.sleep(self.pause_s)
        return antwort.json()


def _sauber(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def zu_stelle(zeile: dict, details: dict | None = None) -> Stelle:
    d = {**zeile, **(details or {})}
    orte = zeile.get("stellenlokationen") or d.get("stellenlokationen") or []
    adresse = (orte[0].get("adresse") if orte else None) or {}
    beschreibung = html.unescape(d.get("stellenangebotsBeschreibung") or "").replace(chr(160), " ")
    firmen_url = d.get("allianzpartnerUrl") or ""
    refnr = d["referenznummer"]
    email = kontakt.beste_email(beschreibung, firmen_url)
    weg, weg_grund = kontakt.bewerbungsweg(beschreibung, email)
    return Stelle(
        quelle=QUELLE,
        refnr=refnr,
        titel=_sauber(d.get("stellenangebotsTitel") or d.get("titel")
                      or (f"Ausbildung: {d['hauptberuf']}" if d.get("hauptberuf") else "")),
        firma=_sauber(d.get("firma") or d.get("arbeitgeber") or ""),
        ort=adresse.get("ort", ""),
        plz=adresse.get("plz", ""),
        entfernung_km=zeile.get("entfernung"),
        beruf=d.get("hauptberuf") or d.get("beruf") or "",
        beschreibung=beschreibung,
        url=DETAIL_URL.format(refnr=refnr),
        externe_url=d.get("externeUrl") or "",
        email=email,
        weg=weg,
        weg_grund=weg_grund,
        zeugnis_verlangt=kontakt.verlangt_zeugnis(beschreibung),
        ansprechpartner=kontakt.ansprechpartner(beschreibung),
        zeitarbeit=bool(d.get("istArbeitnehmerUeberlassung")),
        minijob=bool(d.get("istGeringfuegigeBeschaeftigung")),
        art="ausbildung" if "AUSBILDUNG" in str(d.get("stellenangebotsart", "")).upper() else "arbeit",
        beginn=(d.get("eintrittszeitraum") or {}).get("von", ""),
        abschluss_gefordert=d.get("geforderterBildungsabschluss") or "",
        vollzeit=d.get("arbeitszeitVollzeit"),
        veroeffentlicht=d.get("datumErsteVeroeffentlichung") or d.get("aktuelleVeroeffentlichungsdatum") or "",
    )
