from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from .anschreiben import Anschreiben
from .stelle import Stelle

_SPERRE = threading.Lock()

ENTWURF = "entwurf"
ENTFERNT = "entfernt"
GESENDET = "gesendet"
FEHLER = "fehler"
OFFEN = "offen"
ABGESCHLOSSEN = "abgeschlossen"


def jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _schreibe_json(pfad: Path, daten) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, pfad)


class Speicher:
    def __init__(self, wurzel: Path):
        self.wurzel = Path(wurzel)
        self.batches = self.wurzel / "batches"
        self.batches.mkdir(parents=True, exist_ok=True)


    def neuer_batch(self) -> dict:
        basis = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        kennung, n = basis, 1
        with _SPERRE:
            while True:
                try:
                    (self.batches / kennung).mkdir()
                    break
                except FileExistsError:
                    n += 1
                    kennung = f"{basis}-{n}"
        batch = {
            "id": kennung,
            "erstellt": jetzt(),
            "status": OFFEN,
            "eintraege": [],
            "ohne_email": [],
            "aussortiert": 0,
            "freigabe": None,
            "sachbearbeitung": None,
            "protokoll": [],
        }
        self.speichere(batch)
        return batch

    def ordner(self, batch_id: str) -> Path:
        if not batch_id or any(c in batch_id for c in "/\\.:"):
            raise ValueError(f"Ungueltige Batch-ID: {batch_id!r}")
        return self.batches / batch_id

    def lade(self, batch_id: str) -> dict:
        pfad = self.ordner(batch_id) / "batch.json"
        if not pfad.exists():
            raise FileNotFoundError(f"Batch {batch_id} existiert nicht")
        batch = json.loads(pfad.read_text(encoding="utf-8"))
        for e in batch.get("eintraege", []):
            if e.get("pdf") and not Path(e["pdf"]).exists():
                hier = self.ordner(batch_id) / "pdf" / Path(e["pdf"]).name
                if hier.exists():
                    e["pdf"] = str(hier)
        return batch

    def speichere(self, batch: dict) -> None:
        with _SPERRE:
            _schreibe_json(self.ordner(batch["id"]) / "batch.json", batch)

    def alle(self) -> list[dict]:
        ergebnis = []
        for pfad in sorted(self.batches.glob("*/batch.json"), reverse=True):
            try:
                ergebnis.append(json.loads(pfad.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return ergebnis

    @staticmethod
    def eintrag(stelle: Stelle, anschreiben: Anschreiben | None, pdf: str = "") -> dict:
        return {
            "stelle": stelle.als_dict(),
            "anschreiben": anschreiben.als_dict() if anschreiben else None,
            "pdf": pdf,
            "status": ENTWURF,
            "gesendet_am": None,
            "fehler": None,
            "vault_notiz": None,
            "rueckmeldung": None,
        }


    @property
    def _historie_pfad(self) -> Path:
        return self.wurzel / "historie.json"

    def historie(self) -> list[dict]:
        if not self._historie_pfad.exists():
            return []
        return json.loads(self._historie_pfad.read_text(encoding="utf-8"))

    def merke_gesendet(self, eintrag: dict, batch_id: str) -> None:
        s = eintrag["stelle"]
        with _SPERRE:
            daten = self.historie()
            daten.append({
                "datum": eintrag["gesendet_am"],
                "batch": batch_id,
                "firma": s["firma"],
                "titel": s["titel"],
                "ort": s["ort"],
                "refnr": s["refnr"],
                "email": s["email"],
                "url": s["url"],
            })
            _schreibe_json(self._historie_pfad, daten)

    def gesperrte_firmen(self, tage: int, heute: date | None = None) -> set[str]:
        grenze = (heute or date.today()) - timedelta(days=tage)
        return {
            h["firma"].strip().lower()
            for h in self.historie()
            if h.get("datum") and date.fromisoformat(h["datum"][:10]) >= grenze
        }

    def bekannte_refnr(self) -> set[str]:
        return {h["refnr"] for h in self.historie()}
