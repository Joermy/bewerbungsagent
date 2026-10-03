from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .llm import LLM
from .profil import Profil
from .stelle import Stelle
from . import kontakt


@dataclass
class Anschreiben:
    betreff: str
    anrede: str
    absaetze: list[str]
    gruss: str = "Mit freundlichen Grüßen"
    maengel: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join([self.anrede, *self.absaetze, self.gruss])

    def als_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def aus_dict(cls, d: dict) -> "Anschreiben":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


SYSTEM = """Du schreibst Anschreiben fuer Bewerbungen in Deutschland, sachlich und konkret.

Regeln:
- Verwende NUR Fakten aus dem Profil. Erfinde keine Abschluesse, Jahre, Firmen, Zertifikate oder Kenntnisse.
- Fehlt eine geforderte Qualifikation im Profil, erwaehne sie nicht und behaupte sie nicht.
- Beziehe dich auf zwei bis drei konkrete Punkte der Anzeige und verbinde sie mit dem Profil.
- 3 bis 4 Absaetze, zusammen 180 bis 320 Woerter. Sie-Form. Keine Floskeln wie "hiermit bewerbe ich mich".
- KEINE Anrede, KEINE Grussformel, KEIN Name am Ende, KEINE Platzhalter in eckigen Klammern.
- Letzter Absatz: Verfuegbarkeit und Bitte um ein Gespraech.
- Steht im Profil ein Abschnitt "Hinweise fuers Anschreiben", befolge ihn - er hat Vorrang vor deinem Stil.
- Noten, Fehlzeiten und Luecken nie von selbst ansprechen.

Arbeitsproben und Portfolio:
- Stehen im Abschnitt "Arbeitsproben" Links und passt die Stelle zu Gestaltung, Web, IT oder Digitalisierung:
  verweise in genau einem Satz darauf und schreibe EINEN Link aus (Portfolio bevorzugt). Sonst keine Links.
- Verlangt die Anzeige einen hoeheren Schulabschluss als vorhanden: den Abschluss nicht erwaehnen,
  stattdessen mit Arbeitsproben und Praxis zeigen, was schon geht.

Bei einem AUSBILDUNGSPLATZ zusaetzlich:
- Betreff: "Bewerbung um einen Ausbildungsplatz als <Beruf>" plus Beginn, falls bekannt.
- Schwerpunkt Motivation und Lernbereitschaft: warum genau dieser Beruf, was schon ausprobiert wurde.
- Keine Berufserfahrung behaupten, die fuer den Ausbildungsberuf spricht, wenn sie nicht im Profil steht.

Antworte NUR mit JSON:
{"betreff": "Bewerbung als <Stellentitel ohne (m/w/d)>", "absaetze": ["...", "...", "..."]}"""


def nutzer_prompt(stelle: Stelle, profil: Profil) -> str:
    art = "Ausbildungsplatz" if stelle.art == "ausbildung" else "Arbeitsstelle"
    beginn = f"\nBeginn: {stelle.beginn}" if stelle.beginn else ""
    links = ([f"Portfolio: {profil.portfolio}"] if profil.portfolio else []) + \
            [f"Arbeitsprobe: {u}" for u in profil.arbeitsproben]
    proben = ("\n\n# Arbeitsproben\n" + "\n".join(links)) if links else ""
    verlangt = f"\nVerlangter Schulabschluss: {stelle.abschluss_gefordert}" if stelle.abschluss_gefordert else ""
    return (
        f"# Profil von {profil.name}\n{profil.text}{proben}\n\n"
        f"# Stelle ({art})\nTitel: {stelle.titel}\nFirma: {stelle.firma}\nOrt: {stelle.ort}{beginn}{verlangt}\n"
        f"Referenznummer: {stelle.refnr}\n\n{stelle.beschreibung[:7000]}"
    )


_PLATZHALTER = re.compile(r"\[[^\]]{2,}\]|\bXY\b|\bXXX\b|<[^>]+>|\{[^}]+\}")
_FLOSKEL_ANFANG = re.compile(r"^\s*(sehr geehrte|liebe|hallo|guten tag)", re.I)
_FLOSKEL_ENDE = re.compile(r"(mit freundlichen gr|freundliche gr|beste gr|viele gr)", re.I)
_MWD = re.compile(r"\s*\((?:m/w/d|w/m/d|m/f/d|d/m/w|m/w/x|gn\*?|all genders?)\)", re.I)


def pruefe(a: Anschreiben, profil: Profil) -> list[str]:
    maengel: list[str] = []
    woerter = sum(len(p.split()) for p in a.absaetze)
    if not 2 <= len(a.absaetze) <= 6:
        maengel.append(f"{len(a.absaetze)} Absaetze")
    if not 120 <= woerter <= 380:
        maengel.append(f"{woerter} Woerter")
    for p in a.absaetze:
        if _PLATZHALTER.search(p):
            maengel.append(f"Platzhalter: {_PLATZHALTER.search(p).group(0)}")
        if _FLOSKEL_ANFANG.search(p):
            maengel.append("Anrede im Text")
        if _FLOSKEL_ENDE.search(p):
            maengel.append("Grussformel im Text")
    if not a.betreff.strip():
        maengel.append("Betreff leer")
    return maengel


def bereinige_absatz(p: str) -> str:
    return re.sub(r"\s+", " ", p).strip()


def erzeuge(stelle: Stelle, profil: Profil, llm: LLM, versuche: int = 2) -> Anschreiben:
    anrede = kontakt.anrede(stelle.ansprechpartner)
    letzter: Anschreiben | None = None
    for _ in range(versuche):
        daten = llm.frage_json(SYSTEM, nutzer_prompt(stelle, profil))
        absaetze = [bereinige_absatz(str(p)) for p in daten.get("absaetze") or [] if str(p).strip()]
        betreff = _MWD.sub("", str(daten.get("betreff") or f"Bewerbung als {stelle.titel}")).strip()
        letzter = Anschreiben(betreff=betreff + _ref(stelle), anrede=anrede, absaetze=absaetze)
        letzter.maengel = pruefe(letzter, profil)
        if not letzter.maengel:
            return letzter
    assert letzter is not None
    return letzter


def _ref(stelle: Stelle) -> str:
    return "" if stelle.quelle == "manuell" else f" - Ref. {stelle.refnr}"


def von_aussen(stelle: Stelle, profil: Profil, betreff: str, absaetze: list[str]) -> Anschreiben:
    a = Anschreiben(
        betreff=_MWD.sub("", betreff).strip() or f"Bewerbung als {stelle.titel}",
        anrede=kontakt.anrede(stelle.ansprechpartner),
        absaetze=[bereinige_absatz(p) for p in absaetze if p.strip()],
    )
    if stelle.refnr not in a.betreff:
        a.betreff += _ref(stelle)
    a.maengel = pruefe(a, profil)
    return a
