"""Projekte aus der eigenen Portfolio-Website in den Lebenslauf holen.

Quelle ist eine URL (https://name.github.io) oder ein lokaler Ordner der Website.
Gesucht wird nach daten/projekte.js (window.PROJEKTE = [...]), projekte.json oder
einer angegebenen .js/.json-Datei. Vorschaubilder landen in profil/bilder/projekte/.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx

KANDIDATEN = ["daten/projekte.js", "data/projects.json", "projekte.json", "projects.json", "daten/projekte.json"]
BILD_ENDUNGEN = ["-800.jpg", "-800.webp", "-1600.jpg", ".jpg", ".png", ".webp", ""]


class ImportFehler(RuntimeError):
    pass


# ---------------------------------------------------------------- JS-Objektliteral -> JSON

def js_zu_json(text: str):
    """Wandelt ein JavaScript-Literal (unquotierte Schluessel, '...'-Strings, Kommentare,
    Komma am Ende) in Python-Daten um. Reicht fuer Datendateien, nicht fuer Code."""
    start = min((i for i in (text.find("["), text.find("{")) if i >= 0), default=-1)
    if start < 0:
        raise ImportFehler("Keine Liste und kein Objekt in der Datei")
    aus: list[str] = []
    i, n = start, len(text)
    tiefe = 0
    while i < n:
        c = text[i]
        if c in "\"'`":
            ende = i + 1
            teile = []
            while ende < n and text[ende] != c:
                if text[ende] == "\\" and ende + 1 < n:
                    teile.append(text[ende:ende + 2])
                    ende += 2
                    continue
                teile.append(text[ende])
                ende += 1
            roh = "".join(teile)
            if c != '"':
                roh = roh.replace("\\'", "'").replace('"', '\\"')
            roh = roh.replace("\n", "\\n")
            aus.append(f'"{roh}"')
            i = ende + 1
            continue
        if text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
            continue
        if text.startswith("/*", i):
            i = text.find("*/", i)
            i = n if i < 0 else i + 2
            continue
        if c in "[{":
            tiefe += 1
        elif c in "]}":
            tiefe -= 1
            # Komma vor schliessender Klammer entfernen
            while aus and aus[-1].strip() == "":
                aus.pop()
            if aus and aus[-1] == ",":
                aus.pop()
        if c.isalpha() or c in "_$":
            m = re.match(r"[A-Za-z_$][\w$]*", text[i:])
            wort = m.group(0)
            rest = text[i + len(wort):].lstrip()
            if rest.startswith(":"):
                aus.append(f'"{wort}"')
            elif wort in ("true", "false", "null"):
                aus.append(wort)
            elif wort == "undefined":
                aus.append("null")
            else:
                raise ImportFehler(f"Unerwartetes Wort in der Datendatei: {wort}")
            i += len(wort)
            continue
        aus.append(c)
        i += 1
        if tiefe == 0:
            break
    try:
        return json.loads("".join(aus))
    except json.JSONDecodeError as fehler:
        raise ImportFehler(f"Datendatei nicht lesbar: {fehler}") from fehler


# ---------------------------------------------------------------- Laden

def _ist_url(quelle: str) -> bool:
    return quelle.startswith(("http://", "https://"))


def _lade_text(quelle: str, client: httpx.Client | None) -> tuple[str, str]:
    """Gibt (Text, Basis) zurueck; Basis ist die Website-Wurzel fuer Bilder und Links."""
    if _ist_url(quelle):
        c = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "bewerbungsagent"})
        if re.search(r"\.(js|json)(\?|$)", quelle):
            antwort = c.get(quelle)
            antwort.raise_for_status()
            basis = re.sub(r"(daten|data)/[^/]+$", "", quelle.split("?")[0])
            return antwort.text, basis.rstrip("/") + "/"
        basis = quelle.rstrip("/") + "/"
        for k in KANDIDATEN:
            try:
                antwort = c.get(urljoin(basis, k))
            except httpx.HTTPError:
                continue
            if antwort.status_code == 200 and ("[" in antwort.text):
                return antwort.text, basis
        raise ImportFehler(f"Unter {basis} keine Projektdaten gefunden ({', '.join(KANDIDATEN)})")
    pfad = Path(quelle).expanduser()
    if pfad.is_file():
        wurzel = pfad.parent.parent if pfad.parent.name in ("daten", "data") else pfad.parent
        return pfad.read_text(encoding="utf-8"), str(wurzel)
    for k in KANDIDATEN:
        if (pfad / k).is_file():
            return (pfad / k).read_text(encoding="utf-8"), str(pfad)
    raise ImportFehler(f"In {pfad} keine Projektdaten gefunden")


def _feld(p: dict, *namen: str, standard=""):
    for n in namen:
        if p.get(n):
            return p[n]
    return standard


def _als_projekt(p: dict, seite: str) -> dict:
    slug = _feld(p, "slug", "id")
    technik = _feld(p, "technologies", "technik", "tech", "stack", standard=[])
    if isinstance(technik, str):
        technik = [t.strip() for t in technik.split(",")]
    detail = urljoin(seite, f"work/{slug}/") if seite and slug and _ist_url(seite) else ""
    return {
        "titel": _feld(p, "title", "titel", "name"),
        "untertitel": _feld(p, "subtitle", "untertitel"),
        "beschreibung": _feld(p, "description", "beschreibung", "summary"),
        "technik": [str(t) for t in technik][:6],
        "url": detail or _feld(p, "url", "website", "link"),
        "github": _feld(p, "github", "repo"),
        "bild": "",
        "_slug": slug,
        "_bild_quelle": _feld(p, "heroImage", "image", "bild", "thumbnail"),
        "_jahr": _feld(p, "year", "jahr"),
    }


def _domain_aus_ordner(ordner: Path) -> str:
    for datei in (ordner / "daten" / "domain.txt", ordner / "CNAME"):
        if datei.is_file():
            zeilen = datei.read_text(encoding="utf-8").split()
            wert = zeilen[0] if zeilen else ""
            if wert:
                return wert if _ist_url(wert) else f"https://{wert}"
    return ""


def _bild_holen(roh: str, basis: str, ziel_ordner: Path, name: str, client: httpx.Client | None) -> str:
    if not roh:
        return ""
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    for endung in BILD_ENDUNGEN:
        kandidat = roh if roh.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else roh + endung
        if _ist_url(basis) or _ist_url(kandidat):
            url = kandidat if _ist_url(kandidat) else urljoin(basis, kandidat)
            try:
                c = client or httpx.Client(timeout=20, follow_redirects=True)
                antwort = c.get(url)
            except httpx.HTTPError:
                continue
            if antwort.status_code != 200 or not antwort.headers.get("content-type", "").startswith("image/"):
                continue
            daten = antwort.content
        else:
            datei = Path(basis) / kandidat
            if not datei.is_file():
                continue
            daten = datei.read_bytes()
        endung_ziel = Path(kandidat).suffix.lower() or ".jpg"
        ziel = ziel_ordner / f"{name}{endung_ziel}"
        ziel.write_bytes(daten)
        return str(ziel)
    return ""


def importiere(quelle: str, wurzel: Path, max_anzahl: int = 6, nur: list[str] | None = None,
               client: httpx.Client | None = None, bilder: bool = True, seite: str = "") -> list[dict]:
    """Liest Projekte und laedt Vorschaubilder. Gibt Lebenslauf-Projekte zurueck (noch nicht gespeichert).

    seite: oeffentliche Adresse der Website, wenn aus einem lokalen Ordner gelesen wird
    (sonst steht sie in daten/domain.txt oder CNAME, falls vorhanden)."""
    text, basis = _lade_text(quelle.strip(), client)
    daten = js_zu_json(text)
    if isinstance(daten, dict):
        daten = daten.get("projekte") or daten.get("projects") or list(daten.values())
    if not isinstance(daten, list):
        raise ImportFehler("Projektdaten sind keine Liste")
    if not seite:
        seite = basis if _ist_url(basis) else _domain_aus_ordner(Path(basis))
    if seite and not seite.endswith("/"):
        seite += "/"
    projekte = [_als_projekt(p, seite) for p in daten if isinstance(p, dict)]
    if nur:
        wahl = {n.lower() for n in nur}
        projekte = [p for p in projekte if p["_slug"].lower() in wahl or p["titel"].lower() in wahl]
    projekte = [p for p in projekte if p["titel"]][:max_anzahl]
    ordner = Path(wurzel) / "profil" / "bilder" / "projekte"
    for p in projekte:
        if bilder:
            name = re.sub(r"[^\w-]+", "-", p["_slug"] or p["titel"]).strip("-").lower() or "projekt"
            gespeichert = _bild_holen(p["_bild_quelle"], basis, ordner, name, client)
            if gespeichert:
                p["bild"] = str(Path(gespeichert).resolve().relative_to(Path(wurzel).resolve())).replace("\\", "/")
        for k in [k for k in p if k.startswith("_")]:
            p.pop(k)
    return projekte


def zusammenfuehren(vorhanden: list[dict], neu: list[dict], ersetzen: bool = False) -> list[dict]:
    """Importierte Projekte kommen nach vorn (in der Reihenfolge der Website). Gleiche Titel werden
    aktualisiert, eigene Texte bleiben dabei erhalten; nur von Hand angelegte Projekte haengen hinten an."""
    if ersetzen:
        return neu
    alt_nach_titel = {p.get("titel", "").lower(): p for p in vorhanden}
    aus = []
    for p in neu:
        alt = alt_nach_titel.pop(p["titel"].lower(), None)
        if alt:
            p = {**p, **{k: v for k, v in alt.items() if v and k in ("beschreibung", "untertitel")}}
        aus.append(p)
    return aus + [p for p in vorhanden if p.get("titel", "").lower() in alt_nach_titel]
