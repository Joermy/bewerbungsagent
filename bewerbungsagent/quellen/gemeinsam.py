"""Gemeinsames fuer weitere Jobquellen: Anzeigen in Stellen umwandeln, Dubletten erkennen."""
from __future__ import annotations

import html
import re
import unicodedata

from .. import kontakt
from ..stelle import Stelle

_ZEITARBEIT = re.compile(
    r"zeitarbeit|arbeitnehmer(ü|ue)berlassung|personaldienstleist|personalvermittlung|"
    r"\b(randstad|adecco|manpower|persona service|orizon|tempton|dis ag|amadeus fire|gi group|timepartner|"
    r"start people|piening|jobactive|unique personalservice|ferchau|brunel)\b", re.I)
_MINIJOB = re.compile(r"minijob|geringf(ü|ue)gig|\b5[23568]\d\s?(€|euro)\b|auf \d{3}\s?(€|euro)[- ]basis", re.I)
_TEILZEIT = re.compile(r"\bteilzeit\b|part[- ]time", re.I)
_VOLLZEIT = re.compile(r"\bvollzeit\b|full[- ]time", re.I)
_AUSBILDUNG = re.compile(r"\bausbildung|azubi|auszubildende|duales studium|ausbildungsplatz", re.I)


def ohne_html(text: str) -> str:
    text = re.sub(r"<\s*(br|/p|/li|/div|/h\d)\s*/?>", "\n", text or "", flags=re.I)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def schluessel(firma: str, titel: str) -> str:
    """Firma + Titel, vereinfacht - dieselbe Anzeige auf zwei Portalen faellt zusammen."""
    def f(t: str) -> str:
        t = unicodedata.normalize("NFKD", (t or "").lower())
        t = "".join(c for c in t if not unicodedata.combining(c))
        t = re.sub(r"\((m|w|d|f|x)(/(m|w|d|f|x))+\)|\b(gmbh|ag|kg|co|mbh|ug|e\.?v|se)\b", " ", t)
        return re.sub(r"[^a-z0-9]+", "", t)
    return f"{f(firma)}|{f(titel)}"


def baue(quelle: str, refnr: str, titel: str, firma: str, beschreibung: str = "", url: str = "", ort: str = "",
         plz: str = "", veroeffentlicht: str = "", vollzeit: bool | None = None, firmen_url: str = "",
         adresse: list[str] | None = None, entfernung_km: int | None = None) -> Stelle:
    beschreibung = ohne_html(beschreibung)
    titel = ohne_html(titel)
    email = kontakt.beste_email(beschreibung, firmen_url)
    weg, weg_grund = kontakt.bewerbungsweg(beschreibung, email)
    if not email:
        weg, weg_grund = "portal", "über den Link der Anzeige bewerben"
    gesamt = f"{titel} {firma} {beschreibung}"
    if vollzeit is None:
        if _VOLLZEIT.search(gesamt) and not _TEILZEIT.search(titel):
            vollzeit = True
        elif _TEILZEIT.search(titel):
            vollzeit = False
    return Stelle(
        quelle=quelle,
        refnr=f"{quelle}-{refnr}",
        titel=titel.strip(),
        firma=(firma or "").strip() or "Unbekannte Firma",
        ort=ort.strip(),
        plz=plz.strip(),
        entfernung_km=entfernung_km,
        beschreibung=beschreibung,
        url=url,
        externe_url=url,
        email=email,
        weg=weg,
        weg_grund=weg_grund,
        zeugnis_verlangt=kontakt.verlangt_zeugnis(beschreibung),
        ansprechpartner=kontakt.ansprechpartner(beschreibung),
        firmen_adresse=adresse or [],
        zeitarbeit=bool(_ZEITARBEIT.search(f"{firma} {beschreibung[:600]}")),
        minijob=bool(_MINIJOB.search(gesamt)),
        vollzeit=vollzeit,
        art="ausbildung" if _AUSBILDUNG.search(titel) else "arbeit",
        veroeffentlicht=(veroeffentlicht or "")[:10],
    )


class QuellenFehler(RuntimeError):
    pass
