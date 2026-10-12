"""Lebenslauf als strukturierte Daten (profil/lebenslauf.yaml).

Aus diesen Daten entstehen Lebenslauf, Deckblatt, Portfolio-Seite und das
Briefpapier des Anschreibens. Der Editor in der App schreibt dieselbe Datei.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import yaml

from .profil import Profil

VORLAGEN = {
    "profil": "Zwei Spalten mit Zeitleiste, Foto und Kenntnis-Skalen",
    "klar": "Eine Spalte, sehr gut maschinenlesbar – für Bewerbungsportale",
    "kontrast": "Dunkle Seitenleiste mit Kontakt und Kenntnissen, kräftiger Auftritt",
}

AKZENTE = {
    "spektrum": ("#9b5cff", "linear-gradient(100deg, #ff7a3d 0%, #ff3d7f 32%, #9b5cff 64%, #38b6ff 100%)"),
    "blau": ("#2552d0", "#2552d0"),
    "petrol": ("#0f6e7a", "#0f6e7a"),
    "wald": ("#2f6b45", "#2f6b45"),
    "bordeaux": ("#8c2341", "#8c2341"),
    "graphit": ("#3d4250", "#3d4250"),
}

SCHRIFTEN = {
    "bricolage": ("Bricolage Grotesque", "Inter"),
    "inter": ("Inter", "Inter"),
    "serif": ("Source Serif 4", "Inter"),
}

ABSCHNITTE = ["kurzprofil", "erfahrung", "projekte", "bildung", "kenntnisse", "sprachen", "zertifikate", "interessen"]

ABSCHNITT_TITEL = {
    "kurzprofil": "Kurzprofil",
    "erfahrung": "Erfahrung",
    "projekte": "Projekte",
    "bildung": "Bildung",
    "kenntnisse": "Kenntnisse",
    "sprachen": "Sprachen",
    "zertifikate": "Weiterbildung",
    "interessen": "Interessen",
}

STANDARD_DESIGN = {
    "vorlage": "profil",
    "akzent": "spektrum",
    "eigene_farbe": "",
    "schrift": "bricolage",
    "foto": True,
    "foto_form": "rund",          # rund | eckig
    "qr": True,                   # QR-Codes bei Projekten
    "projekt_bilder": True,
    "skalen": "punkte",           # punkte | balken | aus
    "abschnitte": list(ABSCHNITTE),
    "ausblenden": [],
    "max_projekte": 4,
    "unterschrift_im_lebenslauf": True,
    "ort_datum": True,
}

LEER = {
    "person": {
        "name": "", "titel": "", "foto": "", "geburtsdatum": "", "geburtsort": "", "strasse": "", "plz_ort": "",
        "telefon": "", "email": "", "web": "", "github": "", "linkedin": "", "fuehrerschein": "", "verfuegbar": "",
    },
    "kurzprofil": "",
    "erfahrung": [],
    "bildung": [],
    "projekte": [],
    "kenntnisse": [],
    "sprachen": [],
    "zertifikate": [],
    "interessen": [],
    "design": STANDARD_DESIGN,
}


def _zusammenfuehren(basis: dict, neu: dict) -> dict:
    aus = copy.deepcopy(basis)
    for k, v in (neu or {}).items():
        if isinstance(v, dict) and isinstance(aus.get(k), dict):
            aus[k] = _zusammenfuehren(aus[k], v)
        else:
            aus[k] = v
    return aus


def normalisiere(daten: dict) -> dict:
    """Fehlende Felder ergaenzen, Listen sauber machen - der Editor darf Teile weglassen."""
    d = _zusammenfuehren(LEER, daten or {})
    d["design"] = _zusammenfuehren(STANDARD_DESIGN, d.get("design") or {})
    design = d["design"]
    bekannte = [a for a in design.get("abschnitte") or [] if a in ABSCHNITTE]
    design["abschnitte"] = bekannte + [a for a in ABSCHNITTE if a not in bekannte]
    if design.get("vorlage") not in VORLAGEN:
        design["vorlage"] = "profil"
    if design.get("akzent") not in AKZENTE and not design.get("eigene_farbe"):
        design["akzent"] = "spektrum"
    if design.get("schrift") not in SCHRIFTEN:
        design["schrift"] = "bricolage"
    for liste in ("erfahrung", "bildung", "projekte", "kenntnisse", "sprachen", "zertifikate"):
        d[liste] = [x for x in (d.get(liste) or []) if isinstance(x, dict)]
    for e in d["erfahrung"] + d["bildung"]:
        e["punkte"] = [str(p).strip() for p in e.get("punkte") or [] if str(p).strip()]
    for p in d["projekte"]:
        p["technik"] = [str(t).strip() for t in p.get("technik") or [] if str(t).strip()]
    for g in d["kenntnisse"]:
        eintraege = []
        for e in g.get("eintraege") or []:
            if isinstance(e, str):
                e = {"name": e, "stufe": 0}
            if e.get("name"):
                eintraege.append({"name": str(e["name"]), "stufe": max(0, min(5, int(e.get("stufe") or 0)))})
        g["eintraege"] = eintraege
    for s in d["sprachen"]:
        s["wert"] = max(0, min(5, int(s.get("wert") or 0)))
    d["interessen"] = [str(i).strip() for i in d.get("interessen") or [] if str(i).strip()]
    return d


def pfad(wurzel: Path) -> Path:
    return Path(wurzel) / "profil" / "lebenslauf.yaml"


def lade(wurzel: Path, profil: Profil | None = None) -> dict:
    datei = pfad(wurzel)
    if datei.exists():
        return normalisiere(yaml.safe_load(datei.read_text(encoding="utf-8")) or {})
    return aus_profil(profil) if profil else normalisiere({})


def speichere(wurzel: Path, daten: dict) -> Path:
    datei = pfad(wurzel)
    datei.parent.mkdir(parents=True, exist_ok=True)
    kopf = ("# Lebenslauf - wird in der App unter \"Lebenslauf\" bearbeitet.\n"
            "# Stufen 0-5 (0 = keine Skala). Reihenfolge der Abschnitte: design.abschnitte\n")
    datei.write_text(kopf + yaml.safe_dump(normalisiere(daten), allow_unicode=True, sort_keys=False, width=110),
                     encoding="utf-8")
    return datei


_ZEITRAUM = re.compile(r"^(?P<text>.*?)(?:,\s*|\s+)(?:seit\s+)?(?P<von>(?:\d{2}/)?\d{4})(?:\s*[-–]\s*(?P<bis>(?:\d{2}/)?\d{4}|heute))?\s*$", re.I)


def aus_profil(profil: Profil) -> dict:
    """Erster Entwurf aus profil.md: Kopfdaten und die Stichpunkte der Abschnitte."""
    d = normalisiere({})
    d["person"].update(name=profil.name, strasse=profil.strasse, plz_ort=profil.plz_ort, telefon=profil.telefon,
                       email=profil.email, web=profil.portfolio)
    abschnitte = _md_abschnitte(profil.text)
    for titel, zeilen in abschnitte.items():
        t = titel.lower()
        if "abschluss" in t or "bildung" in t or "schule" in t:
            for z in zeilen:
                d["bildung"].append(_station(z, "abschluss"))
        elif "erfahrung" in t or "praxis" in t:
            for z in zeilen:
                d["erfahrung"].append(_station(z, "titel"))
        elif "stärke" in t or "staerke" in t or "fähig" in t or "kenntnis" in t:
            d["kenntnisse"].append({"gruppe": titel, "eintraege": [{"name": z, "stufe": 0} for z in zeilen]})
        elif "ziel" in t and not d["kurzprofil"]:
            d["kurzprofil"] = " ".join(zeilen)
    for url in profil.arbeitsproben:
        d["projekte"].append({"titel": re.sub(r"^https?://|/$", "", url), "url": url, "beschreibung": "",
                              "technik": [], "bild": ""})
    return d


def _station(zeile: str, feld: str) -> dict:
    treffer = _ZEITRAUM.match(zeile)
    if treffer:
        return {feld: treffer.group("text").strip(" ,"), "von": treffer.group("von"),
                "bis": treffer.group("bis") or ("heute" if "seit" in zeile.lower() else ""), "punkte": []}
    return {feld: zeile.strip(), "von": "", "bis": "", "punkte": []}


def _md_abschnitte(text: str) -> dict[str, list[str]]:
    aus: dict[str, list[str]] = {}
    aktuell = None
    for zeile in text.splitlines():
        if zeile.startswith("#"):
            aktuell = zeile.lstrip("#").strip()
            aus[aktuell] = []
        elif aktuell and zeile.strip().startswith(("-", "*")):
            punkt = zeile.strip()[1:].strip()
            if punkt and punkt != "...":
                aus[aktuell].append(punkt)
    return aus


def als_text(d: dict) -> str:
    """Klartext des Lebenslaufs - fuer ATS-Abgleich und Modell-Prompts."""
    p = d["person"]
    zeilen = [p.get("name", ""), p.get("titel", ""), d.get("kurzprofil", "")]
    for e in d["erfahrung"]:
        zeilen.append(f"{e.get('titel', '')} {e.get('firma', '')} {e.get('ort', '')} "
                      f"{zeitraum(str(e.get('von') or ''), str(e.get('bis') or ''))}")
        zeilen += e.get("punkte") or []
    for e in d["bildung"]:
        zeilen.append(f"{e.get('abschluss', '')} {e.get('schule', '')} "
                      f"{zeitraum(str(e.get('von') or ''), str(e.get('bis') or ''))}")
        zeilen += e.get("punkte") or []
    for pr in d["projekte"]:
        zeilen.append(f"{pr.get('titel', '')} {pr.get('untertitel', '')} {pr.get('beschreibung', '')}")
        zeilen.append(" ".join(pr.get("technik") or []))
    for g in d["kenntnisse"]:
        zeilen.append(f"{g.get('gruppe', '')}: " + ", ".join(e["name"] for e in g["eintraege"]))
    zeilen.append(", ".join(f"{s.get('name', '')} {s.get('stufe', '')}" for s in d["sprachen"]))
    zeilen.append(", ".join(f"{z.get('name', '')} {z.get('aussteller', '')}" for z in d["zertifikate"]))
    zeilen.append(", ".join(d["interessen"]))
    zeilen.append(p.get("fuehrerschein", ""))
    return "\n".join(z for z in zeilen if z and z.strip())


def zeitraum(von: str, bis: str) -> str:
    def fmt(w: str) -> str:
        w = (w or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}", w):
            return f"{w[5:]}/{w[:4]}"
        return w
    von, bis = fmt(von), fmt(bis)
    if von and bis:
        return f"{von} – {bis}"
    return von or bis
