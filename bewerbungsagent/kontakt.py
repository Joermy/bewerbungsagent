from __future__ import annotations

import re
from urllib.parse import urlparse

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

_VERSCHLEIERT = [
    (re.compile(r"\s*[\(\[\{]\s*(?:at|ät)\s*[\)\]\}]\s*", re.I), "@"),
    (re.compile(r"\s*[\(\[\{]\s*(?:dot|punkt)\s*[\)\]\}]\s*", re.I), "."),
]

_UNBRAUCHBAR = ("noreply", "no-reply", "donotreply", "datenschutz", "privacy", "example.")
_BEVORZUGT = ("bewerb", "karriere", "career", "jobs", "job@", "personal", "hr@", "recruiting", "talent")

_NAME = r"[^\W\d_](?:[^\W\d_]|-(?=[^\W\d_]))+"
_ANREDE = re.compile(rf"\b(Frau|Herrn?)\s+((?:Dr\.\s+)?(?=[A-ZÄÖÜÀ-Ý]){_NAME}(?:\s+(?=[A-ZÄÖÜÀ-Ý]){_NAME})?)")


def entschleiern(text: str) -> str:
    for muster, ersatz in _VERSCHLEIERT:
        text = muster.sub(ersatz, text)
    return text


def emails(text: str) -> list[str]:
    gefunden: list[str] = []
    for treffer in _EMAIL.findall(entschleiern(text or "")):
        adresse = treffer.strip(".").lower()
        if any(u in adresse for u in _UNBRAUCHBAR):
            continue
        if adresse not in gefunden:
            gefunden.append(adresse)
    return gefunden


def _domain(url: str) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = urlparse(url).hostname or ""
    return host.removeprefix("www.").lower()


def beste_email(text: str, firmen_url: str = "") -> str:
    kandidaten = emails(text)
    if not kandidaten:
        return ""
    domain = _domain(firmen_url)

    def rang(adresse: str) -> tuple[int, int]:
        bevorzugt = any(b in adresse for b in _BEVORZUGT)
        passt = bool(domain) and (adresse.endswith("@" + domain) or adresse.endswith("." + domain))
        return (int(bevorzugt) + int(passt), -kandidaten.index(adresse))

    return max(kandidaten, key=rang)


_PORTAL = re.compile(
    r"online[- ]?bewerbung|bewerbungsportal|bewerberportal|karriereportal|jobportal|bewerbungsformular"
    r"|online[- ]?formular|\bjobs\.personio\.|softgarden|\bsuccessfactors\b|\bworkday\b|\bumantis\b"
    r"|onapply|dvinci|interamt|auf diese stelle bewerben|jetzt (online )?bewerben|ausschlie(ss|ß)lich online",
    re.I,
)
_PER_MAIL = re.compile(
    r"per e-?mail|via e-?mail|per mail|an folgende (e-?mail|adresse)|bewerbung(sunterlagen)? (bitte |gerne )?an\s"
    r"|(schick|send)(e|en|t)? (uns )?(deine|ihre)[^.]{0,60}an\s",
    re.I,
)
_KEINE_MAIL = re.compile(
    r"(per|via|über|ueber) e-?mail[^.\n]{0,60}(nicht|leider)|nicht (per|via) e-?mail"
    r"|keine[^.\n]{0,40}(bewerbung|unterlagen)[^.\n]{0,40}(per|via) e-?mail",
    re.I,
)
_NUR_FRAGEN = re.compile(r"fragen|auskünfte|auskunft|rückfragen|informationen zur (stelle|ausbildung)", re.I)
_ZEUGNIS = re.compile(r"(schul|abschluss|halbjahres|jahres|zwischen)zeugnis|letzte[sn]? zeugnis|zeugnisse", re.I)


def _umfeld(text: str, email: str, vorher: int = 260) -> str:
    stelle = text.lower().find(email.lower())
    return text[max(0, stelle - vorher):stelle] if stelle >= 0 else ""


def bewerbungsweg(text: str, email: str) -> tuple[str, str]:
    if not email:
        return "keine", "keine Adresse im Anzeigentext"
    text = text or ""
    if _KEINE_MAIL.search(text):
        return "portal", "Anzeige schließt Bewerbungen per E-Mail aus"
    saetze = _saetze(_umfeld(text, email))
    eigener = saetze[-1] if saetze else ""
    davor = " ".join(saetze[-2:])
    if _NICHT_FUER_BEWERBER.search(eigener):
        return "portal", "Adresse ist für Dienstleister-Anfragen, nicht für Bewerbungen"
    portal_hier = _PORTAL.search(eigener)
    if portal_hier and not _PER_MAIL.search(eigener):
        return "portal", f"Anzeige verlangt Bewerbung über Portal ('{portal_hier.group(0)}')"
    if _BEWERBUNG.search(eigener):
        return "email", ""
    if _NUR_FRAGEN.search(davor):
        return "portal", "Adresse nur für Rückfragen angegeben"
    portal = _PORTAL.search(text)
    if portal and not _PER_MAIL.search(davor):
        return "portal", f"Anzeige verlangt Bewerbung über Portal ('{portal.group(0)}')"
    return "email", ""


_BEWERBUNG = re.compile(r"bewerb|unterlagen|lebenslauf", re.I)
_NICHT_FUER_BEWERBER = re.compile(r"dienstleistung|dienstleister|agentur|vermittler|personalberat|kooperation", re.I)
_ABKUERZUNG = re.compile(r"\b(Tel|Nr|Str|bzw|ggf|evtl|inkl|zzgl|ca|z\.\s?B|u\.\s?a|z\.\s?H|Fa|Hr|Fr|Dr)\.", re.I)


def _saetze(text: str) -> list[str]:
    geschuetzt = _ABKUERZUNG.sub(lambda m: m.group(0).replace(".", "․"), text)
    return [s for s in re.split(r"(?<=[.!?])\s+|\n{2,}", geschuetzt) if s.strip()]


def verlangt_zeugnis(text: str) -> bool:
    return bool(_ZEUGNIS.search(text or ""))


def ansprechpartner(text: str) -> str:
    treffer = _ANREDE.search(text or "")
    if not treffer:
        return ""
    return f"{'Herr' if treffer.group(1) == 'Herrn' else treffer.group(1)} {treffer.group(2)}"


_ZUSATZ = {"la", "le", "de", "di", "da", "del", "van", "von", "zu", "ten", "ter", "al", "el"}


def anrede(ansprechpartner_: str) -> str:
    teile = ansprechpartner_.split()
    if len(teile) < 2 or teile[0] not in ("Frau", "Herr"):
        return "Sehr geehrte Damen und Herren,"
    titel = "Dr. " if "Dr." in teile else ""
    namen = [t for t in teile[1:] if t != "Dr."]
    nachname = " ".join(namen[-2:]) if len(namen) >= 2 and namen[-2].lower() in _ZUSATZ else namen[-1]
    name = f"{teile[0]} {titel}{nachname}"
    return f"Sehr geehrte {name}," if teile[0] == "Frau" else f"Sehr geehrter {name},"
