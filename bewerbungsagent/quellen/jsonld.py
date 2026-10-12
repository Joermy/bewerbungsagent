"""Stellenanzeige von einer beliebigen Seite uebernehmen.

Fast jede Karriereseite und Jobboerse beschreibt ihre Anzeigen fuer Suchmaschinen als
schema.org/JobPosting in JSON-LD. Diese Daten liest das Modul - aus einer URL, aus dem
HTML einer Seite oder aus dem, was das Lesezeichen "Übernehmen" im Browser mitschickt.

Seiten, die automatische Abrufe sperren (Captcha, Bot-Schutz), werden nicht umgangen:
dann im Browser oeffnen und das Lesezeichen nutzen.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser

import httpx

from ..stelle import Stelle
from .gemeinsam import QuellenFehler, baue, ohne_html

QUELLE = "link"
KOPF = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) bewerbungsagent",
        "Accept-Language": "de-DE,de;q=0.9"}
_SPERRE = re.compile(r"captcha|cf-chl|challenge-platform|are you a robot|bist du ein mensch|"
                     r"zugriff verweigert|access denied|unusual traffic", re.I)


class _Leser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld: list[str] = []
        self.meta: dict[str, str] = {}
        self.titel = ""
        self._in_ld = False
        self._in_titel = False
        self._puffer: list[str] = []
        self.text: list[str] = []
        self._still = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_ld, self._puffer = True, []
        elif tag in ("script", "style", "noscript", "nav", "footer", "header", "svg"):
            self._still += 1
        elif tag == "title":
            self._in_titel = True
        elif tag == "meta":
            name = (a.get("property") or a.get("name") or "").lower()
            if name in ("og:title", "og:description", "og:site_name", "description", "og:url"):
                self.meta[name] = a.get("content") or ""
        elif tag in ("p", "li", "h1", "h2", "h3", "br", "div"):
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
            self.ld.append("".join(self._puffer))
        elif tag in ("script", "style", "noscript", "nav", "footer", "header", "svg") and self._still:
            self._still -= 1
        elif tag == "title":
            self._in_titel = False

    def handle_data(self, data):
        if self._in_ld:
            self._puffer.append(data)
        elif self._in_titel:
            self.titel += data
        elif not self._still:
            self.text.append(data)


def _jobpostings(obj) -> list[dict]:
    funde = []
    if isinstance(obj, list):
        for x in obj:
            funde += _jobpostings(x)
    elif isinstance(obj, dict):
        typ = obj.get("@type")
        typen = typ if isinstance(typ, list) else [typ]
        if "JobPosting" in typen:
            funde.append(obj)
        for schluessel in ("@graph", "mainEntity", "itemListElement", "item"):
            if schluessel in obj:
                funde += _jobpostings(obj[schluessel])
    return funde


def _text(wert) -> str:
    if isinstance(wert, dict):
        return str(wert.get("name") or wert.get("value") or wert.get("@id") or "")
    if isinstance(wert, list):
        return ", ".join(_text(w) for w in wert if w)
    return str(wert or "")


def aus_daten(jp: dict, url: str = "") -> Stelle:
    """Eine JobPosting-Struktur (schema.org) in eine Stelle umwandeln."""
    firma = jp.get("hiringOrganization") or {}
    firmen_url = (_text(firma.get("sameAs")) or _text(firma.get("url"))) if isinstance(firma, dict) else ""
    orte = jp.get("jobLocation") or {}
    ort = orte[0] if isinstance(orte, list) and orte else orte
    adr = (ort.get("address") if isinstance(ort, dict) else {}) or {}
    if isinstance(adr, str):
        adr = {"addressLocality": adr}
    strasse = adr.get("streetAddress") or ""
    plz = str(adr.get("postalCode") or "")
    stadt = adr.get("addressLocality") or ""
    art = _text(jp.get("employmentType")).upper()
    kennung = _text(jp.get("identifier")) or hashlib.sha1((url or jp.get("title", "")).encode()).hexdigest()[:16]
    beschreibung = jp.get("description") or ""
    for feld, titel in (("qualifications", "Anforderungen"), ("responsibilities", "Aufgaben"),
                        ("educationRequirements", "Abschluss"), ("experienceRequirements", "Erfahrung")):
        if jp.get(feld) and _text(jp[feld]) not in beschreibung:
            beschreibung += f"\n\n{titel}:\n{_text(jp[feld])}"
    kontakt = jp.get("applicationContact") or {}
    if isinstance(kontakt, dict) and kontakt.get("email"):
        beschreibung += f"\n\nBewerbung an: {kontakt['email']}"
    return baue(
        QUELLE, re.sub(r"\W+", "", kennung)[:40] or "x",
        _text(jp.get("title")), _text(firma) if isinstance(firma, dict) else str(firma),
        beschreibung=beschreibung, url=jp.get("url") or url, ort=stadt, plz=plz,
        veroeffentlicht=str(jp.get("datePosted") or ""),
        vollzeit=True if "FULL_TIME" in art else False if "PART_TIME" in art else None,
        firmen_url=firmen_url, adresse=[z for z in (strasse, f"{plz} {stadt}".strip()) if z],
    )


def aus_text(titel: str, firma: str, text: str, url: str = "") -> Stelle:
    kennung = hashlib.sha1((url or titel).encode()).hexdigest()[:16]
    return baue(QUELLE, kennung, titel, firma, beschreibung=text, url=url)


def aus_html(seite: str, url: str = "") -> Stelle:
    leser = _Leser()
    leser.feed(seite)
    for roh in leser.ld:
        try:
            daten = json.loads(roh.strip().rstrip(";"))
        except json.JSONDecodeError:
            continue
        treffer = _jobpostings(daten)
        if treffer:
            return aus_daten(treffer[0], url)
    if _SPERRE.search(seite[:20000]) and len(seite) < 60000:
        raise QuellenFehler("Die Seite verlangt eine Bestätigung im Browser. Anzeige dort öffnen und "
                            "das Lesezeichen „Übernehmen“ nutzen.")
    titel = leser.meta.get("og:title") or leser.titel.strip()
    if not titel:
        raise QuellenFehler("Auf der Seite steht keine erkennbare Stellenanzeige")
    text = ohne_html("".join(leser.text))
    firma = leser.meta.get("og:site_name", "")
    return aus_text(titel.split(" | ")[0].split(" - ")[0], firma, text[:12000], url)


def aus_url(url: str, client: httpx.Client | None = None) -> Stelle:
    if not re.match(r"^https?://", url or ""):
        raise QuellenFehler("Bitte eine vollständige Adresse mit https:// angeben")
    c = client or httpx.Client(timeout=25, follow_redirects=True, headers=KOPF)
    try:
        antwort = c.get(url)
    except httpx.HTTPError as fehler:
        raise QuellenFehler(f"Seite nicht erreichbar: {fehler}") from fehler
    if antwort.status_code in (401, 403, 429, 503):
        raise QuellenFehler(f"Die Seite lässt keine automatischen Abrufe zu (HTTP {antwort.status_code}). "
                            "Anzeige im Browser öffnen und das Lesezeichen „Übernehmen“ nutzen.")
    antwort.raise_for_status()
    return aus_html(antwort.text, str(antwort.url))
