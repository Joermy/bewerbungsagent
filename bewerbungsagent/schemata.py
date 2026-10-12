"""JSON-Schemata je Aufgabe. LM Studio und Ollama erzwingen damit die Form der
Antwort per Grammatik - kleine Modelle liefern so kein kaputtes JSON mehr."""
from __future__ import annotations


def _liste(min_: int = 0, max_: int = 10, max_laenge: int = 120) -> dict:
    return {"type": "array", "items": {"type": "string", "maxLength": max_laenge}, "minItems": min_, "maxItems": max_}


BEWERTUNG = {
    "type": "object",
    "properties": {"punkte": {"type": "integer", "minimum": 0, "maximum": 100},
                   "begruendung": {"type": "string", "maxLength": 240}},
    "required": ["punkte", "begruendung"],
    "additionalProperties": False,
}

ANSCHREIBEN = {
    "type": "object",
    "properties": {"betreff": {"type": "string", "maxLength": 160},
                   "absaetze": _liste(3, 5, 1100)},
    "required": ["betreff", "absaetze"],
    "additionalProperties": False,
}

ANSCHREIBEN_ANALYSE = {
    "type": "object",
    "properties": {
        "firma": {"type": "string", "maxLength": 240},
        "anforderungen": _liste(3, 3, 90),
        "belege": _liste(3, 3, 260),
        "motivation": {"type": "string", "maxLength": 240},
        "arbeitsprobe": {"type": "boolean"},
    },
    "required": ["firma", "anforderungen", "belege", "motivation", "arbeitsprobe"],
    "additionalProperties": False,
}

ANSCHREIBEN_VIER = {
    "type": "object",
    "properties": {"betreff": {"type": "string", "maxLength": 160},
                   "absaetze": _liste(4, 4, 900)},
    "required": ["betreff", "absaetze"],
    "additionalProperties": False,
}

ATS_SCHLUESSELWOERTER = {
    "type": "object",
    "properties": {k: _liste(0, 10, 60) for k in ("fach", "werkzeuge", "persoenlich", "formal")},
    "required": ["fach", "werkzeuge", "persoenlich", "formal"],
    "additionalProperties": False,
}

ATS_KURZPROFIL = {
    "type": "object",
    "properties": {"kurzprofil": {"type": "string", "maxLength": 600}, "genutzt": _liste(0, 15, 60)},
    "required": ["kurzprofil", "genutzt"],
    "additionalProperties": False,
}

STICHPUNKTE = {
    "type": "object",
    "properties": {"stichpunkte": _liste(1, 12, 200)},
    "required": ["stichpunkte"],
    "additionalProperties": False,
}

JE_AUFGABE = {
    "bewertung": BEWERTUNG,
    "anschreiben": ANSCHREIBEN,
    "anschreiben_analyse": ANSCHREIBEN_ANALYSE,
    "anschreiben_schreiben": ANSCHREIBEN_VIER,
    "ats_schluesselwoerter": ATS_SCHLUESSELWOERTER,
    "ats_kurzprofil": ATS_KURZPROFIL,
    "stichpunkte": STICHPUNKTE,
}
