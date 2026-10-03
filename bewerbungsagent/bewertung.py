from __future__ import annotations

import re
from dataclasses import dataclass

from .llm import LLM, KeinModell, LLMFehler
from .profil import Profil
from .stelle import Stelle

_WORT = re.compile(r"[a-zäöüß][a-zäöüß0-9+#\-]{2,}", re.I)
_FUELLWOERTER = set(
    """und oder der die das den dem des ein eine einer eines mit fuer für von bei auf aus
    als auch sich sie ihr ihre wir uns unser unsere sind ist wird werden haben hat
    zum zur im in an am zu über ueber nach vor sowie oder nicht mehr gerne gute sehr
    m/w/d mwd bieten suchen erwarten aufgaben profil deine dein ihnen ihren kontakt""".split()
)
_MINIJOB = re.compile(r"\b(minijob|aushilfe|geringfügig|520|538|556)\b", re.I)


def woerter(text: str) -> set[str]:
    return {w.lower() for w in _WORT.findall(text or "")} - _FUELLWOERTER


_STUFE_PROFIL = {"kein": 0, "hauptschule": 1, "realschule": 2, "fachabitur": 3, "abitur": 4}
_STUFE_API = [("KEIN", 0), ("HAUPTSCHUL", 1), ("MITTLERE", 2), ("REALSCHUL", 2), ("FACHHOCHSCHUL", 3),
              ("ABITUR", 4), ("HOCHSCHULREIFE", 4)]


def _stufe_api(wert: str) -> int | None:
    wert = (wert or "").upper()
    return next((stufe for wort, stufe in _STUFE_API if wort in wert), None)


def abschluss_text(wert: str) -> str:
    return {0: "keinen Abschluss", 1: "Hauptschulabschluss", 2: "Mittlere Reife", 3: "Fachhochschulreife",
            4: "Abitur"}.get(_stufe_api(wert), wert.replace("_", " ").title())


def abschluss_luecke(s: Stelle, profil: Profil) -> int:
    gefordert = _stufe_api(s.abschluss_gefordert)
    eigen = _STUFE_PROFIL.get(profil.schulabschluss)
    if gefordert is None or eigen is None:
        return 0
    return max(0, gefordert - eigen)


@dataclass
class Aussortiert:
    stelle: Stelle
    grund: str


def regeln(
    stellen: list[Stelle],
    profil: Profil,
    ohne_zeitarbeit: bool,
    ohne_minijob: bool,
    gesperrte_firmen: set[str],
) -> tuple[list[Stelle], list[Aussortiert]]:
    behalten: list[Stelle] = []
    raus: list[Aussortiert] = []
    firmen: set[str] = set()
    for s in stellen:
        firma = s.firma.strip().lower()
        titel = s.titel.lower()
        grund = ""
        if any(a.lower() in titel for a in profil.ausschluss):
            grund = "Ausschlusswort im Titel"
        elif ohne_zeitarbeit and s.zeitarbeit:
            grund = "Zeitarbeit"
        elif ohne_minijob and (s.minijob or _MINIJOB.search(s.titel)):
            grund = "Minijob"
        elif profil.arbeitszeit == "vollzeit" and s.vollzeit is False:
            grund = "keine Vollzeit"
        elif profil.arbeitszeit == "teilzeit" and s.vollzeit is True:
            grund = "keine Teilzeit"
        elif abschluss_luecke(s, profil) >= 2 and not profil.portfolio:
            grund = f"verlangt {abschluss_text(s.abschluss_gefordert)}"
        elif firma in gesperrte_firmen:
            grund = "Firma innerhalb der Sperrfrist schon angeschrieben"
        elif firma in firmen:
            grund = "Firma schon in diesem Lauf"
        if grund:
            raus.append(Aussortiert(s, grund))
        else:
            firmen.add(firma)
            behalten.append(s)
    return behalten, raus


def _stamm_treffer(titel: str, suchbegriffe: list[str], laenge: int = 5) -> bool:
    titelwoerter = re.findall(r"[a-zäöüß]+", titel)
    for begriff in suchbegriffe:
        for wort in re.findall(r"[a-zäöüß]+", begriff.lower()):
            if len(wort) >= laenge and any(t.startswith(wort[:laenge]) for t in titelwoerter):
                return True
    return False


def heuristik(stelle: Stelle, profil: Profil) -> int:
    punkte = 0
    titel = f"{stelle.titel} {stelle.beruf}".lower()
    if any(b.lower() in titel for b in profil.suchbegriffe):
        punkte += 40
    elif _stamm_treffer(titel, profil.suchbegriffe):
        punkte += 30
    profilwoerter = woerter(profil.text) | woerter(" ".join(profil.suchbegriffe))
    anzeige = woerter(stelle.beschreibung)
    if profilwoerter and anzeige:
        punkte += min(50, int(200 * len(profilwoerter & anzeige) / max(len(profilwoerter), 1)))
    if stelle.per_mail:
        punkte += 10
    luecke = abschluss_luecke(stelle, profil)
    if luecke:
        punkte -= (8 if profil.portfolio else 15) * luecke
    return max(0, min(punkte, 100))


BEWERTUNG_SYSTEM = """Du bewertest, wie gut eine Stellenanzeige zu einem Bewerberprofil passt.
Antworte NUR mit JSON: {"punkte": <0-100>, "begruendung": "<ein Satz auf Deutsch>"}
Massstab: 80+ = Anforderungen weitgehend erfuellt; 50-79 = machbar mit Einarbeitung;
unter 50 = wesentliche Anforderung fehlt (Abschluss, Fuehrerschein, Berufserfahrung in Jahren).
Bewerte streng nach dem Profil. Erfinde keine Qualifikationen."""


def mit_llm(stelle: Stelle, profil: Profil, llm: LLM) -> tuple[int, str]:
    nutzer = (
        f"# Profil\n{profil.text}\n\n# Stelle\n{stelle.titel} bei {stelle.firma}, {stelle.ort}\n\n"
        f"{stelle.beschreibung[:6000]}"
    )
    antwort = llm.frage_json(BEWERTUNG_SYSTEM, nutzer)
    return max(0, min(100, int(antwort.get("punkte", 0)))), str(antwort.get("begruendung", ""))[:300]


def sortiere(
    stellen: list[Stelle],
    profil: Profil,
    llm: LLM | None = None,
    llm_kandidaten: int = 16,
    melde=print,
) -> list[Stelle]:
    for s in stellen:
        s.punkte = heuristik(s, profil)
        s.begruendung = "Heuristik"
    stellen.sort(key=lambda s: s.punkte, reverse=True)
    if llm is None:
        return stellen
    for i, s in enumerate(stellen[:llm_kandidaten], 1):
        try:
            s.punkte, s.begruendung = mit_llm(s, profil, llm)
            melde(f"  [{i}/{min(llm_kandidaten, len(stellen))}] {s.punkte:3d}  {s.titel[:50]} - {s.firma[:30]}")
        except KeinModell:
            break
        except LLMFehler as fehler:
            melde(f"  Bewertung fehlgeschlagen, Heuristik bleibt: {fehler}")
    stellen.sort(key=lambda s: s.punkte, reverse=True)
    return stellen
