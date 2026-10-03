from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Stelle:
    quelle: str
    refnr: str
    titel: str
    firma: str
    ort: str = ""
    plz: str = ""
    entfernung_km: int | None = None
    beruf: str = ""
    beschreibung: str = ""
    url: str = ""
    externe_url: str = ""
    email: str = ""
    ansprechpartner: str = ""
    firmen_adresse: list[str] = field(default_factory=list)
    zeitarbeit: bool = False
    minijob: bool = False
    vollzeit: bool | None = None
    veroeffentlicht: str = ""
    art: str = "arbeit"
    beginn: str = ""
    abschluss_gefordert: str = ""
    weg: str = ""
    weg_grund: str = ""
    zeugnis_verlangt: bool = False
    punkte: int = 0
    begruendung: str = ""

    @property
    def per_mail(self) -> bool:
        return bool(self.email) and self.weg in ("", "email")

    @property
    def schluessel(self) -> str:
        return f"{self.quelle}:{self.refnr}"

    def als_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def aus_dict(cls, d: dict) -> "Stelle":
        felder = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in felder})
