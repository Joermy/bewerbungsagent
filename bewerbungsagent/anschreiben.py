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


# Ersatz, falls der Prompt-Ordner fehlt; die gepflegte Fassung liegt in prompts/anschreiben.md
SYSTEM = """Du schreibst Anschreiben fuer Bewerbungen in Deutschland, sachlich und konkret.

Regeln:
- Verwende NUR Fakten aus dem Profil. Erfinde keine Abschluesse, Jahre, Firmen, Zertifikate oder Kenntnisse.
- Fehlt eine geforderte Qualifikation im Profil, erwaehne sie nicht und behaupte sie nicht.
- Beziehe dich auf zwei bis drei konkrete Punkte der Anzeige und verbinde sie mit dem Profil.
- 3 bis 4 Absaetze, zusammen 180 bis 320 Woerter. Sie-Form. Keine Floskeln wie "hiermit bewerbe ich mich".
- KEINE Anrede, KEINE Grussformel, KEIN Name am Ende, KEINE Platzhalter in eckigen Klammern.
- Letzter Absatz: Verfuegbarkeit und Bitte um ein Gespraech.

Antworte NUR mit JSON:
{"betreff": "Bewerbung als <Stellentitel ohne (m/w/d)>", "absaetze": ["...", "...", "..."]}"""


def regeln(llm: LLM | None = None) -> str:
    """Die aktuell gueltigen Regeln - fuer Agenten ueber MCP."""
    if llm is not None and hasattr(llm, "prompt"):
        return llm.prompt("anschreiben", SYSTEM)
    return SYSTEM


def _grenzen(llm) -> tuple[int, int]:
    if hasattr(llm, "einstellung"):
        e = llm.einstellung("anschreiben")
        return e.anzeige_zeichen, e.profil_zeichen
    return 7000, 7000


def _links(profil: Profil) -> list[str]:
    return ([f"Portfolio: {profil.portfolio}"] if profil.portfolio else []) + \
           [f"Arbeitsprobe: {u}" for u in profil.arbeitsproben]


def _kuerze(text: str, zeichen: int) -> str:
    if len(text) <= zeichen:
        return text
    schnitt = text[:zeichen]
    ende = max(schnitt.rfind("\n"), schnitt.rfind(". "))
    return (schnitt[: ende + 1] if ende > zeichen * 0.6 else schnitt).rstrip() + " …"


def nutzer_prompt(stelle: Stelle, profil: Profil, anzeige_zeichen: int = 7000, profil_zeichen: int = 7000) -> str:
    art = "Ausbildungsplatz" if stelle.art == "ausbildung" else "Arbeitsstelle"
    beginn = f"\nBeginn: {stelle.beginn}" if stelle.beginn else ""
    links = _links(profil)
    proben = ("\n\n# Arbeitsproben\n" + "\n".join(links)) if links else ""
    verlangt = f"\nVerlangter Schulabschluss: {stelle.abschluss_gefordert}" if stelle.abschluss_gefordert else ""
    lebenslauf = f"\n\n# Lebenslauf (Auszug)\n{_kuerze(profil.zusatz, min(profil_zeichen, 2400))}" if profil.zusatz else ""
    return (
        f"# Profil von {profil.name}\n{_kuerze(profil.text, profil_zeichen)}{lebenslauf}{proben}\n\n"
        f"# Stelle ({art})\nTitel: {stelle.titel}\nFirma: {stelle.firma}\nOrt: {stelle.ort}{beginn}{verlangt}\n"
        f"Referenznummer: {stelle.refnr}\n\n{_kuerze(stelle.beschreibung, anzeige_zeichen)}"
    )


_PLATZHALTER = re.compile(r"\[[^\]]{2,}\]|\bXY\b|\bXXX\b|<[^>]+>|\{[^}]+\}")
_FLOSKEL_ANFANG = re.compile(r"^\s*(sehr geehrte|liebe|hallo|guten tag)", re.I)
_FLOSKEL_ENDE = re.compile(r"(mit freundlichen gr|freundliche gr|beste gr|viele gr)", re.I)
_FLOSKELN = re.compile(r"hiermit bewerbe ich mich|mit großem interesse|teamfähig, belastbar", re.I)
_MWD = re.compile(r"\s*\((?:m/w/d|w/m/d|m/f/d|d/m/w|m/w/x|gn\*?|all genders?)\)", re.I)

# Faktencheck: Jahreszahlen, Prozentangaben und typische Nachweise, die im Profil stehen muessen
_JAHR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_ZAHL_EINHEIT = re.compile(r"\b\d+[.,]?\d*\s?(?:%|Prozent|Jahre[n]?|Monate[n]?|Kunden|Projekte[n]?)\b", re.I)
_NACHWEIS = re.compile(r"\b(?:Zertifikat|zertifiziert|Diplom|Bachelor|Master|Meister|Studium|Staatsexamen|"
                       r"Führerschein|Staplerschein|IHK-Prüfung|Abitur|Fachabitur|Ausbilderschein)\w*", re.I)


def faktencheck(absaetze: list[str], profil: Profil, anzeige: str = "") -> list[str]:
    """Findet Angaben, die weder im Profil noch in der Anzeige stehen - typische Erfindungen kleiner Modelle."""
    belegt = (profil.text + " " + profil.zusatz + " " + " ".join(profil.arbeitsproben) + " " + profil.portfolio).lower()
    quelle = belegt + " " + anzeige.lower()
    funde: list[str] = []
    text = " ".join(absaetze)
    for treffer in _JAHR.findall(text):
        if treffer not in quelle:
            funde.append(f"Jahr {treffer}")
    for treffer in _ZAHL_EINHEIT.findall(text):
        zahl = re.match(r"\d+", treffer).group(0)
        if zahl not in quelle:
            funde.append(treffer.strip())
    for treffer in _NACHWEIS.findall(text):
        if treffer.lower()[:7] not in belegt:
            funde.append(treffer)
    return sorted(set(funde))


def pruefe(a: Anschreiben, profil: Profil, anzeige: str = "") -> list[str]:
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
        if _FLOSKELN.search(p):
            maengel.append(f"Floskel: {_FLOSKELN.search(p).group(0)}")
    if not a.betreff.strip():
        maengel.append("Betreff leer")
    for fund in faktencheck(a.absaetze, profil, anzeige):
        maengel.append(f"nicht im Profil belegt: {fund}")
    return maengel


def bereinige_absatz(p: str) -> str:
    return re.sub(r"\s+", " ", p).strip()


def _einstufig(stelle: Stelle, profil: Profil, llm: LLM) -> dict:
    anzeige, prof = _grenzen(llm)
    system = regeln(llm)
    if hasattr(llm, "einstellung"):
        return llm.frage_json(system, nutzer_prompt(stelle, profil, anzeige, prof), aufgabe="anschreiben")
    return llm.frage_json(system, nutzer_prompt(stelle, profil, anzeige, prof))


def _mehrstufig(stelle: Stelle, profil: Profil, llm: LLM) -> dict:
    """Fuer kleine Modelle: erst auswerten und Belege zuordnen, dann schreiben."""
    anzeige, prof = _grenzen(llm)
    eingabe = nutzer_prompt(stelle, profil, anzeige, prof)
    analyse = llm.frage_json(llm.prompt("anschreiben_analyse"), eingabe, aufgabe="anschreiben_analyse")
    # Belege, die nicht im Profil stehen, verwerfen (Modell hat sie erfunden)
    belege = [str(b) for b in analyse.get("belege") or []]
    pruef = (profil.text + " " + profil.zusatz).lower()
    gepr = []
    for b in belege:
        kern = [w for w in re.findall(r"[a-zäöüß]{5,}", b.lower())]
        gepr.append(b if b and kern and sum(w in pruef for w in kern) >= max(1, len(kern) // 3) else "")
    analyse["belege"] = gepr
    links = _links(profil)
    auswertung = (
        f"# AUSWERTUNG\nFirma: {analyse.get('firma', '')}\n"
        + "\n".join(f"Anforderung {i + 1}: {a}\nBeleg {i + 1}: {b or '(keiner)'}"
                    for i, (a, b) in enumerate(zip(analyse.get("anforderungen") or [], gepr)))
        + f"\nMotivation: {analyse.get('motivation', '')}\narbeitsprobe: {str(bool(analyse.get('arbeitsprobe'))).lower()}\n"
        + (("Arbeitsproben:\n" + "\n".join(links)) if links else "Arbeitsproben: keine")
        + f"\n\n# STELLE\nTitel: {stelle.titel}\nFirma: {stelle.firma}\nArt: "
        + ("Ausbildungsplatz" + (f", Beginn {stelle.beginn}" if stelle.beginn else "") if stelle.art == "ausbildung" else "Arbeitsstelle")
        + f"\n\n# PROFIL (Auszug)\n{_kuerze(profil.text, min(prof, 1800))}"
    )
    return llm.frage_json(llm.prompt("anschreiben_schreiben"), auswertung, aufgabe="anschreiben_schreiben")


def erzeuge(stelle: Stelle, profil: Profil, llm: LLM, versuche: int = 2) -> Anschreiben:
    anrede = kontakt.anrede(stelle.ansprechpartner)
    letzter: Anschreiben | None = None
    stufig = bool(getattr(llm, "mehrstufig", False))
    for _ in range(versuche):
        daten = _mehrstufig(stelle, profil, llm) if stufig else _einstufig(stelle, profil, llm)
        absaetze = [bereinige_absatz(str(p)) for p in daten.get("absaetze") or [] if str(p).strip()]
        betreff = _MWD.sub("", str(daten.get("betreff") or f"Bewerbung als {stelle.titel}")).strip()
        letzter = Anschreiben(betreff=betreff + _ref(stelle), anrede=anrede, absaetze=absaetze)
        letzter.maengel = pruefe(letzter, profil, f"{stelle.beschreibung} {stelle.beginn}")
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
    a.maengel = pruefe(a, profil, f"{stelle.beschreibung} {stelle.beginn}")
    return a
