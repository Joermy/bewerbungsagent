"""Setzt Lebenslauf, Anschreiben, Deckblatt und Portfolio-Seite als HTML.

Dasselbe HTML dient als Live-Vorschau in der App und als Druckvorlage fuer das PDF.
Bilder werden als data:-URI eingebettet, damit die Vorschau im iframe (srcdoc)
und der Druck aus einer Temp-Datei gleich aussehen.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from . import lebenslauf as lv

VORLAGEN = Path(__file__).parent / "vorlagen"
SCHRIFTEN = Path(__file__).parent / "statisch" / "schriften"
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]


@lru_cache(maxsize=1)
def _icons() -> dict[str, str]:
    return json.loads((VORLAGEN / "icons.json").read_text(encoding="utf-8"))


def icon(name: str, groesse: float = 3.4, klasse: str = "ic") -> Markup:
    inner = _icons().get(name) or _icons()["circle-check"]
    return Markup(
        f'<svg class="{klasse}" viewBox="0 0 24 24" width="{groesse}mm" height="{groesse}mm" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{inner}</svg>'
    )


def qr(url: str, groesse: float = 15) -> Markup:
    if not url:
        return Markup("")
    try:
        import segno
    except ImportError:
        return Markup("")
    code = segno.make(url, error="m")
    svg = code.svg_inline(scale=1, border=0, dark="#1c1e26", omitsize=True)
    svg = svg.replace("<svg ", f'<svg class="qr" width="{groesse}mm" height="{groesse}mm" ', 1)
    return Markup(svg)


def kurz_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?|/$", "", url or "")


def bild_uri(pfad: str, wurzel: Path) -> str:
    if not pfad:
        return ""
    if pfad.startswith(("data:", "http://", "https://")):
        return pfad
    datei = Path(pfad)
    if not datei.is_absolute():
        datei = wurzel / datei
    if not datei.exists():
        return ""
    typ = mimetypes.guess_type(datei.name)[0] or "image/jpeg"
    return f"data:{typ};base64,{base64.b64encode(datei.read_bytes()).decode()}"


def schrift_css(modus: str) -> str:
    """@font-face fuer Vorschau (ueber den App-Server) oder Druck (eingebettet)."""
    dateien = {
        "Inter": ("inter.woff2", "inter-ext.woff2", "100 900"),
        "Bricolage Grotesque": ("bricolage.woff2", "bricolage-ext.woff2", "200 800"),
        "Source Serif 4": ("sourceserif.woff2", "sourceserif-ext.woff2", "200 900"),
    }
    teile = []
    for familie, (grund, ext, gewicht) in dateien.items():
        for datei, bereich in ((grund, "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, "
                                       "U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, "
                                       "U+2212, U+2215, U+FEFF, U+FFFD"),
                               (ext, "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, "
                                     "U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, "
                                     "U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF")):
            if modus == "vorschau":
                quelle = f"/statisch/schriften/{datei}"
            else:
                quelle = "data:font/woff2;base64," + base64.b64encode((SCHRIFTEN / datei).read_bytes()).decode()
            teile.append(f"@font-face{{font-family:'{familie}';src:url({quelle}) format('woff2');"
                         f"font-weight:{gewicht};font-style:normal;font-display:block;unicode-range:{bereich}}}")
    return "\n".join(teile)


def _farben(design: dict) -> dict:
    if design.get("eigene_farbe") and re.fullmatch(r"#[0-9a-fA-F]{6}", design["eigene_farbe"]):
        farbe = design["eigene_farbe"]
        return {"akzent": farbe, "band": farbe, "spektrum": False}
    farbe, band = lv.AKZENTE.get(design.get("akzent"), lv.AKZENTE["spektrum"])
    return {"akzent": farbe, "band": band, "spektrum": design.get("akzent") == "spektrum"}


def datum_deutsch(tag: date) -> str:
    return f"{tag.day}. {MONATE[tag.month - 1]} {tag.year}"


def _umgebung() -> Environment:
    env = Environment(loader=FileSystemLoader(str(VORLAGEN)), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.globals.update(icon=icon, qr=qr, kurz_url=kurz_url, zeitraum=lv.zeitraum, titel=lv.ABSCHNITT_TITEL,
                       ort_zeile=lambda *t: ", ".join(str(x) for x in t if x))
    env.filters["absatz"] = lambda t: Markup("".join(f"<p>{escape(x.strip())}</p>" for x in str(t or "").split("\n\n") if x.strip()))
    return env


_ENV = None


def env() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = _umgebung()
    return _ENV


def _kontext(d: dict, wurzel: Path, modus: str) -> dict:
    d = lv.normalisiere(d)
    design = d["design"]
    kopf, text = lv.SCHRIFTEN[design["schrift"]]
    alle = [dict(p) for p in d["projekte"]]
    for p in alle:
        p["bild_uri"] = bild_uri(p.get("bild", ""), wurzel) if design.get("projekt_bilder") else ""
    projekte = alle[: int(design.get("max_projekte") or 4)]
    return {
        "d": d,
        "p": d["person"],
        "design": design,
        "farben": _farben(design),
        "kopfschrift": kopf,
        "textschrift": text,
        "foto": bild_uri(d["person"].get("foto", ""), wurzel) if design.get("foto") else "",
        "projekte": projekte,
        "alle_projekte": alle,
        "abschnitte": [a for a in design["abschnitte"] if a not in (design.get("ausblenden") or [])],
        "schriften": Markup(schrift_css(modus)),
        "css": Markup((VORLAGEN / "dokument.css").read_text(encoding="utf-8")),
        "seiten_js": Markup((VORLAGEN / "seiten.js").read_text(encoding="utf-8")),
        "modus": modus,
        "heute": datum_deutsch(date.today()),
    }


def lebenslauf(d: dict, wurzel: Path, modus: str = "druck") -> str:
    k = _kontext(d, wurzel, modus)
    return env().get_template(f"lebenslauf_{k['design']['vorlage']}.html.j2").render(**k)


def anschreiben(d: dict, wurzel: Path, brief: dict, modus: str = "druck", schriftgrad: float = 10.5) -> str:
    """brief: empfaenger (Zeilen), betreff, referenz, anrede, absaetze, gruss, ort_datum, anlagen, unterschrift."""
    k = _kontext(d, wurzel, modus)
    b = dict(brief)
    b["unterschrift_uri"] = bild_uri(b.get("unterschrift", ""), wurzel)
    return env().get_template("anschreiben.html.j2").render(**k, b=b, schriftgrad=schriftgrad)


def deckblatt(d: dict, wurzel: Path, angaben: dict, modus: str = "druck") -> str:
    k = _kontext(d, wurzel, modus)
    return env().get_template("deckblatt.html.j2").render(**k, a=angaben)


def portfolio(d: dict, wurzel: Path, modus: str = "druck") -> str:
    k = _kontext(d, wurzel, modus)
    return env().get_template("portfolio.html.j2").render(**k)
