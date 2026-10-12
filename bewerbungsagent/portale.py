"""Portal-Zentrale: die wichtigsten Jobboersen an einer Stelle, mit eigenem Status.

Anmelden muss man sich selbst - Konten, Passwoerter und Captchas bleiben beim Menschen.
Die Liste sagt, wie der Agent das Portal nutzt (API, Jobalarm per Mail, Lesezeichen),
und merkt sich in daten/portale.json, wo man schon ein Konto und einen Alarm hat.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

# weg: api = sucht selbst, mail = liest Jobalarme aus dem Postfach, lesezeichen = Übernehmen im Browser
PORTALE: list[dict] = [
    {"id": "arbeitsagentur", "name": "Jobbörse der Arbeitsagentur", "url": "https://www.arbeitsagentur.de/jobsuche/",
     "art": "Jobbörse", "wege": ["api", "mail", "lesezeichen"],
     "tipp": "Wird automatisch durchsucht. Ein Konto braucht es nur für eigene Suchaufträge und das Bewerberprofil."},
    {"id": "indeed", "name": "Indeed", "url": "https://de.indeed.com/", "art": "Jobbörse",
     "wege": ["mail", "lesezeichen"],
     "tipp": "Suche speichern und Jobalarm per E-Mail einschalten - der Agent liest die Alarme aus dem Postfach."},
    {"id": "stepstone", "name": "StepStone", "url": "https://www.stepstone.de/", "art": "Jobbörse",
     "wege": ["mail", "lesezeichen"], "tipp": "Job-Agent per E-Mail anlegen; einzelne Anzeigen mit „Übernehmen“."},
    {"id": "linkedin", "name": "LinkedIn Jobs", "url": "https://www.linkedin.com/jobs/", "art": "Netzwerk",
     "wege": ["mail", "lesezeichen"], "tipp": "Jobbenachrichtigung per E-Mail aktivieren."},
    {"id": "xing", "name": "XING Jobs", "url": "https://www.xing.com/jobs", "art": "Netzwerk",
     "wege": ["mail", "lesezeichen"], "tipp": "Suchauftrag speichern, Benachrichtigung per E-Mail."},
    {"id": "monster", "name": "Monster", "url": "https://www.monster.de/", "art": "Jobbörse",
     "wege": ["mail", "lesezeichen"], "tipp": "Jobagent per E-Mail."},
    {"id": "glassdoor", "name": "Glassdoor", "url": "https://www.glassdoor.de/", "art": "Jobbörse",
     "wege": ["mail", "lesezeichen"], "tipp": "Jobalarm per E-Mail; Firmenbewertungen vor dem Gespräch lesen."},
    {"id": "adzuna", "name": "Adzuna", "url": "https://www.adzuna.de/", "art": "Suchmaschine",
     "wege": ["api", "lesezeichen"], "tipp": "Kostenlosen API-Schlüssel auf developer.adzuna.com holen und in .env eintragen."},
    {"id": "jooble", "name": "Jooble", "url": "https://de.jooble.org/", "art": "Suchmaschine",
     "wege": ["api", "lesezeichen"], "tipp": "API-Schlüssel auf jooble.org/api/about anfragen und in .env eintragen."},
    {"id": "kimeta", "name": "kimeta", "url": "https://www.kimeta.de/", "art": "Suchmaschine",
     "wege": ["lesezeichen"], "tipp": "Sammelt Anzeigen von Firmenseiten - gut für kleine Betriebe in der Region."},
    {"id": "meinestadt", "name": "meinestadt.de", "url": "https://jobs.meinestadt.de/", "art": "Regional",
     "wege": ["lesezeichen"], "tipp": "Viele regionale Stellen und Ausbildungsplätze."},
    {"id": "stellenanzeigen", "name": "stellenanzeigen.de", "url": "https://www.stellenanzeigen.de/", "art": "Jobbörse",
     "wege": ["lesezeichen"], "tipp": ""},
    {"id": "jobware", "name": "Jobware", "url": "https://www.jobware.de/", "art": "Jobbörse",
     "wege": ["lesezeichen"], "tipp": ""},
    {"id": "azubiyo", "name": "AZUBIYO", "url": "https://www.azubiyo.de/", "art": "Ausbildung",
     "wege": ["lesezeichen"], "tipp": "Ausbildungsplätze und duale Studiengänge, mit Eignungstest."},
    {"id": "ausbildungde", "name": "Ausbildung.de", "url": "https://www.ausbildung.de/", "art": "Ausbildung",
     "wege": ["lesezeichen"], "tipp": ""},
    {"id": "aubiplus", "name": "AUBI-plus", "url": "https://www.aubi-plus.de/", "art": "Ausbildung",
     "wege": ["lesezeichen"], "tipp": ""},
    {"id": "ihk", "name": "IHK-Lehrstellenbörse", "url": "https://www.ihk-lehrstellenboerse.de/", "art": "Ausbildung",
     "wege": ["lesezeichen"], "tipp": "Ausbildungsplätze in IHK-Berufen, direkt von den Betrieben."},
    {"id": "lehrstellenradar", "name": "Lehrstellen-Radar (Handwerk)", "url": "https://www.lehrstellen-radar.de/",
     "art": "Ausbildung", "wege": ["lesezeichen"], "tipp": "Ausbildung im Handwerk."},
    {"id": "getinit", "name": "get in IT", "url": "https://www.get-in-it.de/", "art": "IT",
     "wege": ["lesezeichen"], "tipp": "Einstieg und Ausbildung in der IT."},
    {"id": "interamt", "name": "Interamt", "url": "https://www.interamt.de/", "art": "Öffentlicher Dienst",
     "wege": ["lesezeichen"], "tipp": "Stellen bei Bund, Ländern und Kommunen."},
    {"id": "bund", "name": "service.bund.de", "url": "https://www.service.bund.de/", "art": "Öffentlicher Dienst",
     "wege": ["lesezeichen"], "tipp": "Stellenangebote des Bundes."},
]

WEGE = {
    "api": "sucht automatisch",
    "mail": "liest Jobalarme aus dem Postfach",
    "lesezeichen": "Anzeigen mit „Übernehmen“ holen, Formulare mit „Ausfüllen“",
}


class Portale:
    def __init__(self, daten: Path):
        self.datei = Path(daten) / "portale.json"

    def _status(self) -> dict:
        if not self.datei.exists():
            return {}
        try:
            return json.loads(self.datei.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def liste(self, cfg=None) -> list[dict]:
        status = self._status()
        aus = []
        for p in PORTALE:
            eintrag = {**p, **{"konto": False, "alarm": False, "notiz": "", "geaendert": ""}, **status.get(p["id"], {})}
            if cfg is not None:
                eintrag["aktiv"] = _aktiv(p["id"], cfg)
            aus.append(eintrag)
        return aus

    def setze(self, portal_id: str, konto: bool | None = None, alarm: bool | None = None,
              notiz: str | None = None) -> dict:
        if portal_id not in {p["id"] for p in PORTALE}:
            raise KeyError(f"Portal {portal_id} unbekannt")
        status = self._status()
        e = status.setdefault(portal_id, {})
        if konto is not None:
            e["konto"] = bool(konto)
        if alarm is not None:
            e["alarm"] = bool(alarm)
        if notiz is not None:
            e["notiz"] = str(notiz)[:300]
        e["geaendert"] = date.today().isoformat()
        self.datei.parent.mkdir(parents=True, exist_ok=True)
        self.datei.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return e


def _aktiv(portal_id: str, cfg) -> str:
    """Wie der Agent das Portal gerade nutzt - fuer die Anzeige in der App."""
    q, k = cfg.quellen, cfg.schluessel
    if portal_id == "arbeitsagentur":
        return "sucht automatisch" if q.arbeitsagentur else "aus"
    if portal_id == "adzuna":
        if q.adzuna and k.adzuna_id:
            return "sucht automatisch"
        return "Schlüssel fehlt" if q.adzuna else "aus"
    if portal_id == "jooble":
        if q.jooble and k.jooble:
            return "sucht automatisch"
        return "Schlüssel fehlt" if q.jooble else "aus"
    p = next(x for x in PORTALE if x["id"] == portal_id)
    if "mail" in p["wege"] and q.mail_alarme:
        return "Jobalarme werden gelesen" if k.imap_host else "Postfach fehlt"
    return "Lesezeichen"
