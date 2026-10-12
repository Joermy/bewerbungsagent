from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Callable

from . import anschreiben as ans
from . import bewertung, kontakt, mail, pdf
from .config import Config
from .drucker import DruckFehler
from .unterlagen import Unterlagen
from .llm import LLM, KeinModell, LLMFehler
from .profil import Profil
from . import profil as profil_mod
from .quellen.arbeitsagentur import ANGEBOTSARTEN, AUSBILDUNG, Arbeitsagentur, zu_stelle
from .quellen.gemeinsam import QuellenFehler, schluessel
from .speicher import ABGESCHLOSSEN, ENTFERNT, ENTWURF, FEHLER, GESENDET, OFFEN, Speicher, jetzt
from .stelle import Stelle
from .vault import Vault

BESTAETIGUNG = "SENDEN"
Melde = Callable[[str], None]


class Abbruch(RuntimeError):
    pass


class Dienst:
    def __init__(self, cfg: Config, quelle: Arbeitsagentur | None = None, llm: LLM | None = None):
        self.cfg = cfg
        self.speicher = Speicher(cfg.daten)
        self.vault = Vault(cfg)
        self._quelle = quelle
        self._llm = llm
        self._profil: Profil | None = None
        self._unterlagen: Unterlagen | None = None

    @property
    def profil(self) -> Profil:
        if self._profil is None:
            self._profil = profil_mod.lade(self.cfg.profil)
            pdf.setze_unterschrift(self._profil, self.cfg.unterschrift)
            from . import lebenslauf as lv
            if lv.pfad(self.cfg.wurzel).exists():
                try:
                    self._profil.zusatz = lv.als_text(lv.lade(self.cfg.wurzel))
                except Exception:
                    pass
        return self._profil

    @property
    def unterlagen(self) -> Unterlagen:
        if self._unterlagen is None or self._unterlagen.profil is not self.profil:
            self._unterlagen = Unterlagen(self.cfg, self.profil)
        return self._unterlagen

    def profil_neu_laden(self) -> None:
        self._profil = None
        self._unterlagen = None

    @property
    def quelle(self) -> Arbeitsagentur:
        if self._quelle is None:
            self._quelle = Arbeitsagentur()
        return self._quelle

    @property
    def llm(self) -> LLM:
        if self._llm is None:
            self._llm = LLM(self.cfg)
        return self._llm

    @property
    def mit_modell(self) -> bool:
        return self.cfg.llm.backend.lower() != "keins"

    def anlagen(self) -> list[Path]:
        return [a for a in self.cfg.anlagen if a.exists()]

    def erzeugt_lebenslauf(self) -> bool:
        try:
            u = self.unterlagen
        except Exception:
            return False
        return self.cfg.dokumente.lebenslauf and u.hat_lebenslauf and u.html_aktiv

    def anhang_uebersicht(self) -> list[str]:
        """Was einer Bewerbung beiliegt - fuer App und Status."""
        teile = []
        if self.erzeugt_lebenslauf():
            teile.append("Lebenslauf (erzeugt)")
            if self.cfg.dokumente.projektseite:
                teile.append("Projektseite (erzeugt)")
            anlagen = self.unterlagen.anlagen_ohne_doppelten_lebenslauf(self.anlagen())
        else:
            anlagen = self.anlagen()
        teile += [a.name for a in anlagen]
        return teile

    def _grenze(self, s: Stelle) -> int:
        su = self.cfg.suche
        return su.mindest_passung if s.begruendung == "Heuristik" else su.mindest_passung_modell


    def suche(self, melde: Melde = print) -> tuple[list[Stelle], int]:
        p = self.profil
        su = self.cfg.suche
        bekannt = self.speicher.bekannte_refnr()
        gesehen: set[str] = set()
        stellen: list[Stelle] = []
        arten = ANGEBOTSARTEN.get(su.angebotsart.lower())
        if not arten:
            raise Abbruch(f"suche.angebotsart muss arbeit, ausbildung oder beides sein, nicht {su.angebotsart!r}")
        auftraege = [(b, a) for a in arten for b in p.suchbegriffe] if self.cfg.quellen.arbeitsagentur else []
        for begriff, art in auftraege:
            name = "Ausbildung" if art == AUSBILDUNG else "Arbeit"
            melde(f"Suche {name} '{begriff}' um {p.wohnort}, {su.umkreis_km} km, letzte {su.veroeffentlicht_seit_tage} Tage")
            treffer = 0
            for zeile in self.quelle.suche(begriff, p.wohnort, su.umkreis_km, su.veroeffentlicht_seit_tage,
                                          su.ohne_zeitarbeit, su.max_treffer_je_begriff, art):
                ref = zeile.get("referenznummer")
                if not ref or ref in gesehen or ref in bekannt:
                    continue
                gesehen.add(ref)
                treffer += 1
                try:
                    details = self.quelle.details(ref)
                except Exception as fehler:
                    melde(f"  Details {ref} nicht ladbar: {fehler}")
                    details = None
                stellen.append(zu_stelle(zeile, details))
            melde(f"  {treffer} neue Anzeigen")
        stellen += self._weitere_stellen(p, melde, bekannt, {schluessel(s.firma, s.titel) for s in stellen})
        behalten, raus = bewertung.regeln(stellen, p, su.ohne_zeitarbeit, su.ohne_minijob,
                                          self.speicher.gesperrte_firmen(su.sperrfrist_tage))
        melde(f"{len(stellen)} Anzeigen, {len(raus)} aussortiert, {len(behalten)} bleiben")
        sortiert = bewertung.sortiere(behalten, p, None)
        if self.mit_modell and sortiert:
            mit_mail = [s for s in sortiert if s.per_mail]
            melde(f"Modell bewertet die besten {min(16, len(mit_mail))} Stellen mit E-Mail-Adresse")
            try:
                bewertung.sortiere(mit_mail, p, self.llm, llm_kandidaten=16, melde=melde)
            except (KeinModell, LLMFehler) as fehler:
                melde(f"  Modell nicht nutzbar, Heuristik bleibt: {fehler}")
            sortiert.sort(key=lambda s: s.punkte, reverse=True)
        return sortiert, len(raus)


    def weitere_quellen(self) -> list:
        """Zusaetzlich zur Arbeitsagentur eingeschaltete Quellen (config.yaml: quellen)."""
        q, k = self.cfg.quellen, self.cfg.schluessel
        liste = []
        if q.adzuna:
            from .quellen.adzuna import Adzuna
            liste.append(lambda: Adzuna(k.adzuna_id, k.adzuna_key, q.land))
        if q.jooble:
            from .quellen.jooble import Jooble
            liste.append(lambda: Jooble(k.jooble))
        return liste

    def _weitere_stellen(self, p: Profil, melde: Melde, bekannt: set[str], gesehen: set[str]) -> list[Stelle]:
        su, q = self.cfg.suche, self.cfg.quellen
        neu: list[Stelle] = []

        def nimm(s: Stelle) -> bool:
            k = schluessel(s.firma, s.titel)
            if s.refnr in bekannt or k in gesehen:
                return False
            gesehen.add(k)
            neu.append(s)
            return True

        for baue in self.weitere_quellen():
            try:
                quelle = baue()
                for begriff in p.suchbegriffe:
                    n = 0
                    for s in quelle.suche(begriff, p.wohnort, su.umkreis_km, su.veroeffentlicht_seit_tage,
                                          q.max_treffer):
                        n += nimm(s)
                    melde(f"{quelle.name} '{begriff}': {n} neue Anzeigen")
            except (QuellenFehler, Exception) as fehler:
                melde(f"  Quelle nicht nutzbar: {fehler}")
        if q.mail_alarme:
            from .quellen.mailalarm import Postfach
            k = self.cfg.schluessel
            try:
                funde = Postfach(k.imap_host, k.imap_user, k.imap_password, k.imap_port, q.mail_ordner).lies(q.mail_tage)
                n = sum(nimm(s) for s in funde)
                melde(f"Jobalarme im Postfach: {len(funde)} Anzeigen, {n} neu")
            except (QuellenFehler, Exception) as fehler:
                melde(f"  Postfach nicht lesbar: {fehler}")
        return neu

    def stelle_aus_link(self, url: str = "", daten: dict | None = None, text: str = "", titel: str = "",
                        firma: str = "", batch_id: str = "", melde: Melde = print) -> dict:
        """Anzeige von einer Webseite uebernehmen (URL, JSON-LD vom Lesezeichen oder markierter Text)
        und als Entwurf in einen Lauf legen - in den angegebenen, den neuesten offenen oder einen neuen."""
        from .quellen import jsonld
        if daten:
            s = jsonld.aus_daten(daten, url)
        elif text:
            s = jsonld.aus_text(titel or "Stelle", firma, text, url)
        else:
            s = jsonld.aus_url(url)
        if batch_id:
            batch = self.speicher.lade(batch_id)
        else:
            offen = [b for b in self.speicher.alle() if b.get("status") == OFFEN]
            batch = self.speicher.lade(offen[0]["id"]) if offen else self.speicher.neuer_batch()
        return self._neuer_eintrag(batch, s, melde)

    def lauf(self, melde: Melde = print) -> dict:
        batch = self.speicher.neuer_batch()
        try:
            stellen, aussortiert = self.suche(melde)
            genug = [s for s in stellen if s.punkte >= self._grenze(s)]
            if len(genug) < len(stellen):
                melde(f"{len(stellen) - len(genug)} Stellen unter der Mindestpassung")
            mit_mail = [s for s in genug if s.per_mail]
            gewaehlt = mit_mail[: self.cfg.suche.anzahl]
            batch["aussortiert"] = aussortiert
            batch["reserve"] = [s.als_dict() for s in mit_mail[self.cfg.suche.anzahl: self.cfg.suche.anzahl + 12]]
            batch["ohne_email"] = [s.als_dict() for s in genug if not s.per_mail][:25]
            for s in gewaehlt:
                batch["eintraege"].append(Speicher.eintrag(s, None))
            batch["protokoll"].append(f"{jetzt()} {len(gewaehlt)} Stellen gewaehlt")
            self.speicher.speichere(batch)
            melde(f"{len(gewaehlt)} Stellen gewaehlt, {len(batch['ohne_email'])} ohne E-Mail zum Selbstbewerben")
            for i in range(len(batch["eintraege"])):
                self._schreibe_text(batch, i, melde)
            self._vault_alles(batch, f"Bewerbungen: Lauf {batch['id']} mit {len(gewaehlt)} Entwuerfen")
            melde("Fertig. Entwuerfe pruefen, dann freigeben.")
        except Exception as fehler:
            batch["protokoll"].append(f"{jetzt()} Abbruch: {fehler}")
            self.speicher.speichere(batch)
            raise
        return batch

    def _schreibe_text(self, batch: dict, i: int, melde: Melde = print) -> None:
        e = batch["eintraege"][i]
        s = Stelle.aus_dict(e["stelle"])
        if not self.mit_modell:
            melde(f"  [{i + 1}] {s.firma}: kein Modell - Text ueber MCP oder App eintragen")
            return
        melde(f"  [{i + 1}/{len(batch['eintraege'])}] Anschreiben fuer {s.firma} ...")
        start = time.monotonic()
        try:
            a = ans.erzeuge(s, self.profil, self.llm)
        except (KeinModell, LLMFehler) as fehler:
            e["fehler"] = f"Text: {fehler}"
            melde(f"      fehlgeschlagen: {fehler}")
            self.speicher.speichere(batch)
            return
        self._setze(batch, i, a)
        hinweis = f" - Maengel: {', '.join(a.maengel)}" if a.maengel else ""
        melde(f"      fertig in {time.monotonic() - start:.0f} s{hinweis}")

    def _setze(self, batch: dict, i: int, a: ans.Anschreiben) -> None:
        e = batch["eintraege"][i]
        s = Stelle.aus_dict(e["stelle"])
        ordner = self.speicher.ordner(batch["id"])
        datei = f"{i + 1:02d}_{mail.dateiname(s.firma)}.pdf"
        u = self.unterlagen
        erg = u.anschreiben(ordner / "pdf" / datei, s, a, u.anlagen_namen(self.anlagen()))
        if not erg.passt:
            a.maengel.append("passt nicht auf eine Seite - kuerzen")
        e["anschreiben"] = a.als_dict()
        e["pdf"] = str(erg.pfad)
        e["layout"] = erg.engine
        e["mappe"] = None
        e["lebenslauf"] = None
        e["fehler"] = None
        try:
            d = u.daten_fuer(e)
            if e.get("kurzprofil") and u.html_aktiv and u.hat_lebenslauf:
                e["lebenslauf"] = str(u.lebenslauf_direkt(ordner / "lebenslauf" / datei, d).pfad)
            if self.cfg.dokumente.anhang.lower() == "mappe" and u.html_aktiv:
                lebenslauf = Path(e["lebenslauf"]) if e["lebenslauf"] else None
                e["mappe"] = str(u.mappe(ordner / "mappe" / datei, s, a, self.anlagen(), erg.pfad, d, lebenslauf).pfad)
        except (DruckFehler, OSError) as fehler:
            e["fehler"] = f"Unterlagen: {fehler}"
        self.speicher.speichere(batch)


    def _offener_eintrag(self, batch_id: str, i: int) -> tuple[dict, dict]:
        batch = self.speicher.lade(batch_id)
        if not 0 <= i < len(batch["eintraege"]):
            raise IndexError(f"Eintrag {i} gibt es nicht")
        e = batch["eintraege"][i]
        if e["status"] == GESENDET:
            raise Abbruch("Schon gesendet - nicht mehr aenderbar")
        return batch, e

    def setze_text(self, batch_id: str, i: int, betreff: str, absaetze: list[str]) -> dict:
        batch, e = self._offener_eintrag(batch_id, i)
        a = ans.von_aussen(Stelle.aus_dict(e["stelle"]), self.profil, betreff, absaetze)
        self._setze(batch, i, a)
        self._vault_eintrag(batch, i)
        return batch["eintraege"][i]

    def setze_kurzprofil(self, batch_id: str, i: int, kurzprofil: str) -> dict:
        """Kurzprofil nur fuer diese Bewerbung (z. B. aus dem ATS-Check); leer = wieder das allgemeine."""
        batch, e = self._offener_eintrag(batch_id, i)
        e["kurzprofil"] = kurzprofil.strip() or None
        if e.get("anschreiben"):
            self._setze(batch, i, ans.Anschreiben.aus_dict(e["anschreiben"]))
        else:
            self.speicher.speichere(batch)
        return batch["eintraege"][i]

    def ats(self, batch_id: str = "", i: int | None = None, titel: str = "", text: str = "",
            mit_modell: bool = False, melde: Melde = print) -> dict:
        from . import ats as ats_mod
        lv_daten = self.unterlagen.daten()
        if batch_id and i is not None:
            e = self.speicher.lade(batch_id)["eintraege"][i]
            titel, text = e["stelle"]["titel"], e["stelle"]["beschreibung"]
            if e.get("kurzprofil"):
                lv_daten["kurzprofil"] = e["kurzprofil"]
        llm = self.llm if (mit_modell and self.mit_modell) else None
        bericht = ats_mod.pruefe(titel, text, lv_daten, self.profil.text, llm, melde)
        return {**bericht.als_dict(), "titel": titel}

    def ats_kurzprofil(self, batch_id: str = "", i: int | None = None, titel: str = "", text: str = "",
                       melde: Melde = print) -> dict:
        from . import ats as ats_mod
        if not self.mit_modell:
            raise Abbruch("Fuer einen Vorschlag braucht es ein Sprachmodell (llm.backend)")
        lv_daten = self.unterlagen.daten()
        if batch_id and i is not None:
            e = self.speicher.lade(batch_id)["eintraege"][i]
            titel, text = e["stelle"]["titel"], e["stelle"]["beschreibung"]
        melde("Schluesselwoerter abgleichen ...")
        bericht = ats_mod.pruefe(titel, text, lv_daten, self.profil.text, self.llm, melde)
        melde("Kurzprofil schreiben ...")
        vorschlag = ats_mod.kurzprofil_vorschlag(bericht, titel, lv_daten, self.profil.text, self.llm)
        return {**vorschlag, "bericht": bericht.als_dict(), "messung": self.llm.letzte.als_dict() if self.llm.letzte else None}

    def neu_schreiben(self, batch_id: str, i: int, melde: Melde = print) -> dict:
        batch, _ = self._offener_eintrag(batch_id, i)
        self._schreibe_text(batch, i, melde)
        self._vault_eintrag(batch, i)
        return batch["eintraege"][i]

    def entferne(self, batch_id: str, i: int, nachruecken: bool = True, melde: Melde = print) -> dict:
        batch, e = self._offener_eintrag(batch_id, i)
        e["status"] = ENTFERNT
        batch["protokoll"].append(f"{jetzt()} entfernt: {e['stelle']['firma']}")
        self.speicher.speichere(batch)
        self._vault_eintrag(batch, i)
        if nachruecken and batch.get("reserve"):
            s = Stelle.aus_dict(batch["reserve"].pop(0))
            batch["eintraege"].append(Speicher.eintrag(s, None))
            batch["protokoll"].append(f"{jetzt()} nachgerueckt: {s.firma}")
            self.speicher.speichere(batch)
            neu = len(batch["eintraege"]) - 1
            self._schreibe_text(batch, neu, melde)
            self._vault_eintrag(batch, neu)
        return batch

    def verwerfen(self, batch_id: str) -> dict:
        batch = self.speicher.lade(batch_id)
        for e in batch["eintraege"]:
            if e["status"] in (ENTWURF, FEHLER):
                e["status"] = ENTFERNT
        batch["status"] = ABGESCHLOSSEN
        batch["protokoll"].append(f"{jetzt()} Lauf verworfen")
        self.speicher.speichere(batch)
        self._vault_alles(batch, f"Bewerbungen: Lauf {batch_id} verworfen")
        return batch

    def rueckmeldung(self, batch_id: str, i: int, art: str) -> dict:
        if art not in ("eingeladen", "absage", "zusage", ""):
            raise ValueError("art: eingeladen | absage | zusage")
        batch = self.speicher.lade(batch_id)
        e = batch["eintraege"][i]
        e["rueckmeldung"] = art or None
        e["rueckmeldung_am"] = jetzt() if art else None
        self.speicher.speichere(batch)
        self._vault_eintrag(batch, i)
        self._vault_uebersicht(f"Bewerbungen: Rueckmeldung {art or 'zurueckgesetzt'} - {e['stelle']['firma']}")
        return e


    def smtp_probleme(self) -> list[str]:
        s = self.cfg.smtp
        if not s.vollstaendig:
            return ["SMTP-Zugang in .env fehlt (SMTP_HOST, SMTP_USER, SMTP_PASSWORD)"]
        probleme = []
        if any(h in s.host.lower() for h in ("outlook.", "office365.", "hotmail.", "live.")):
            probleme.append("Outlook/Hotmail nimmt seit 2026 keine SMTP-Anmeldung mit Passwort mehr an "
                            "- Gmail mit App-Passwort nutzen")
        try:
            profil_mail = self.profil.email.strip().lower()
        except Exception:
            profil_mail = ""
        if profil_mail and "@" in s.user and s.user.strip().lower() != profil_mail:
            probleme.append(f"Absenderkonto {s.user} passt nicht zur Profil-Adresse {profil_mail}")
        return probleme


    def uebernehmen(self, batch_id: str, refnr: str, melde: Melde = print) -> dict:
        batch = self.speicher.lade(batch_id)
        liste = batch.get("ohne_email") or []
        treffer = next((s for s in liste if s["refnr"] == refnr), None)
        if treffer is None:
            raise KeyError(f"Stelle {refnr} steht nicht unter 'Selbst bewerben'")
        liste.remove(treffer)
        return self._neuer_eintrag(batch, Stelle.aus_dict(treffer), melde)

    def hinzufuegen(self, batch_id: str, firma: str, titel: str, beschreibung: str = "", email: str = "",
                    ort: str = "", url: str = "", art: str = "arbeit", ansprechpartner: str = "",
                    melde: Melde = print) -> dict:
        if not firma.strip() or not titel.strip():
            raise ValueError("Firma und Stellentitel sind Pflicht")
        email = email.strip()
        if email and not kontakt.emails(email):
            raise ValueError(f"Keine gueltige E-Mail-Adresse: {email}")
        batch = self.speicher.lade(batch_id)
        s = Stelle(
            quelle="manuell", refnr=f"manuell-{jetzt().replace(':', '').replace('-', '')}",
            titel=titel.strip(), firma=firma.strip(), ort=ort.strip(), url=url.strip(),
            beschreibung=beschreibung.strip(), email=email.lower(),
            ansprechpartner=ansprechpartner.strip() or kontakt.ansprechpartner(beschreibung),
            art="ausbildung" if art == "ausbildung" else "arbeit",
            weg="email" if email else "portal",
            weg_grund="von Hand angelegt" if email else "von Hand angelegt, keine Adresse",
            zeugnis_verlangt=kontakt.verlangt_zeugnis(beschreibung), begruendung="von Hand",
        )
        return self._neuer_eintrag(batch, s, melde)

    def _neuer_eintrag(self, batch: dict, s: Stelle, melde: Melde) -> dict:
        batch["eintraege"].append(Speicher.eintrag(s, None))
        batch["status"] = OFFEN
        batch["protokoll"].append(f"{jetzt()} von Hand: {s.firma}")
        self.speicher.speichere(batch)
        i = len(batch["eintraege"]) - 1
        self._schreibe_text(batch, i, melde)
        self._vault_eintrag(batch, i)
        return batch

    def setze_adresse(self, batch_id: str, i: int, email: str) -> dict:
        gefunden = kontakt.emails(email)
        if not gefunden:
            raise ValueError(f"Keine gueltige E-Mail-Adresse: {email}")
        batch, e = self._offener_eintrag(batch_id, i)
        e["stelle"].update(email=gefunden[0], weg="email", weg_grund="Adresse von Hand eingetragen")
        self.speicher.speichere(batch)
        self._vault_eintrag(batch, i)
        return e

    def als_beworben(self, batch_id: str, i: int, weg: str = "portal") -> dict:
        if weg not in ("portal", "post", "persoenlich"):
            raise ValueError("weg: portal | post | persoenlich")
        batch, e = self._offener_eintrag(batch_id, i)
        e["status"], e["gesendet_am"], e["kanal"], e["fehler"] = GESENDET, jetzt(), weg, None
        self.speicher.speichere(batch)
        self.speicher.merke_gesendet(e, batch_id)
        self._vault_eintrag(batch, i)
        self._vault_uebersicht(f"Bewerbungen: {e['stelle']['firma']} selbst beworben ({weg})")
        return e


    def _auswahl(self, batch: dict, nur: list[int] | None) -> list[int]:
        offen = [i for i, e in enumerate(batch["eintraege"]) if e["status"] in (ENTWURF, FEHLER)]
        if nur is None:
            return [i for i in offen if Stelle.aus_dict(batch["eintraege"][i]["stelle"]).per_mail]
        falsch = [i for i in nur if i not in offen]
        if falsch:
            raise Abbruch(f"Eintrag {falsch} ist nicht offen")
        return list(nur)

    def pruefe_versand(self, batch: dict, nur: list[int] | None = None) -> list[str]:
        probleme = list(self.smtp_probleme())
        try:
            auswahl = self._auswahl(batch, nur)
        except Abbruch as fehler:
            return probleme + [str(fehler)]
        if not auswahl:
            probleme.append("keine offenen Bewerbungen mit E-Mail-Adresse im Lauf")
        for i in auswahl:
            e = batch["eintraege"][i]
            name = e["stelle"]["firma"]
            if not e.get("anschreiben") or not e.get("pdf") or not Path(e["pdf"]).exists():
                probleme.append(f"{name}: Anschreiben fehlt")
            if not Stelle.aus_dict(e["stelle"]).per_mail:
                probleme.append(f"{name}: keine Bewerbungsadresse ({e['stelle'].get('weg_grund') or 'fehlt'})")
        if not self.anlagen() and not self.erzeugt_lebenslauf():
            probleme.append("kein Lebenslauf: profil/lebenslauf.yaml in der App anlegen "
                            "oder eine PDF unter 'anlagen' in config.yaml eintragen")
        return probleme

    def senden(self, batch_id: str, bestaetigung: str, melde: Melde = print, pause_s: float = 3.0,
               nur: list[int] | None = None) -> dict:
        if bestaetigung != BESTAETIGUNG:
            raise Abbruch(f"Bestaetigung fehlt: bitte woertlich {BESTAETIGUNG} eingeben")
        batch = self.speicher.lade(batch_id)
        probleme = self.pruefe_versand(batch, nur)
        if probleme:
            raise Abbruch("; ".join(probleme))
        auswahl = self._auswahl(batch, nur)
        batch["freigabe"] = {"zeit": jetzt(), "anzahl": len(auswahl)}
        self.speicher.speichere(batch)

        p = self.profil
        bcc = p.email if self.cfg.mail.kopie_an_mich else ""
        eml = self.speicher.ordner(batch_id) / "gesendet"
        eml.mkdir(parents=True, exist_ok=True)
        gesendet_jetzt = 0
        with mail.Versand(self.cfg.smtp) as versand:
            for i in auswahl:
                e = batch["eintraege"][i]
                s = e["stelle"]
                try:
                    msg = mail.bewerbungsmail(p, e, self.anlagen(), self.cfg.mail.absender_name, bcc,
                                              anhaenge=self.unterlagen.anhaenge(e, self.anlagen()))
                    versand.schicke(msg)
                    e["status"], e["gesendet_am"], e["kanal"], e["fehler"] = GESENDET, jetzt(), "email", None
                    (eml / f"{i + 1:02d}_{mail.dateiname(s['firma'])}.eml").write_bytes(bytes(msg))
                    self.speicher.merke_gesendet(e, batch_id)
                    gesendet_jetzt += 1
                    melde(f"gesendet: {s['firma']} <{s['email']}>")
                except Exception as fehler:
                    e["status"], e["fehler"] = FEHLER, str(fehler)[:300]
                    melde(f"FEHLER {s['firma']}: {fehler}")
                self.speicher.speichere(batch)
                self._vault_eintrag(batch, i)
                time.sleep(pause_s)
            self._nachweis(batch, versand, bcc, melde)

        if all(e["status"] in (GESENDET, ENTFERNT) for e in batch["eintraege"]):
            batch["status"] = ABGESCHLOSSEN
        batch["protokoll"].append(f"{jetzt()} Versand: {gesendet_jetzt} gesendet")
        self.speicher.speichere(batch)
        melde(self._vault_uebersicht(f"Bewerbungen: {gesendet_jetzt} gesendet (Lauf {batch_id})"))
        return batch

    def ungemeldet(self, batch: dict) -> list[dict]:
        return [e for e in batch["eintraege"] if e["status"] == GESENDET and not e.get("gemeldet")]

    def nachweis_senden(self, batch_id: str, bestaetigung: str, melde: Melde = print) -> dict:
        if bestaetigung != BESTAETIGUNG:
            raise Abbruch(f"Bestaetigung fehlt: bitte woertlich {BESTAETIGUNG} eingeben")
        probleme = self.smtp_probleme()
        if probleme:
            raise Abbruch("; ".join(probleme))
        batch = self.speicher.lade(batch_id)
        if not self.ungemeldet(batch):
            raise Abbruch("Alles aus diesem Lauf ist der Sachbearbeitung schon gemeldet")
        bcc = self.profil.email if self.cfg.mail.kopie_an_mich else ""
        with mail.Versand(self.cfg.smtp) as versand:
            self._nachweis(batch, versand, bcc, melde)
        self.speicher.speichere(batch)
        return batch

    def _nachweis(self, batch: dict, versand, bcc: str, melde: Melde) -> None:
        ziel = self.cfg.mail.sachbearbeitung
        offen = self.ungemeldet(batch)
        if not offen:
            return
        if not ziel:
            melde("Keine Sachbearbeitungs-Adresse in config.yaml - Nachweis nicht verschickt")
            return
        heute = date.today()
        nr = len(batch.get("nachweise") or []) + 1
        nachweis = pdf.nachweis_pdf(
            self.speicher.ordner(batch["id"]) / f"Bewerbungsnachweis_{nr}.pdf", self.profil,
            [{"datum": e["gesendet_am"][:10], "kanal": e.get("kanal") or "email", **e["stelle"]} for e in offen],
            heute)
        msg = mail.nachweismail(self.profil, ziel, offen, nachweis, heute.strftime("%d.%m.%Y"),
                                self.cfg.mail.absender_name, bcc)
        try:
            versand.schicke(msg)
        except Exception as fehler:
            melde(f"FEHLER Nachweis an Sachbearbeitung: {fehler}")
            return
        ablage = self.speicher.ordner(batch["id"]) / "gesendet"
        ablage.mkdir(parents=True, exist_ok=True)
        (ablage / f"00_Sachbearbeitung_{nr}.eml").write_bytes(bytes(msg))
        for e in offen:
            e["gemeldet"] = jetzt()
        eintrag = {"zeit": jetzt(), "an": ziel, "anzahl": len(offen)}
        batch.setdefault("nachweise", []).append(eintrag)
        batch["sachbearbeitung"] = eintrag
        melde(f"Nachweis mit {len(offen)} Bewerbungen an Sachbearbeitung gesendet")


    def _vault_eintrag(self, batch: dict, i: int) -> None:
        rel = self.vault.schreibe_stelle(batch["eintraege"][i], batch)
        if rel and batch["eintraege"][i].get("vault_notiz") != rel:
            batch["eintraege"][i]["vault_notiz"] = rel
            self.speicher.speichere(batch)

    def _vault_uebersicht(self, nachricht: str) -> str:
        if not self.vault.aktiv:
            return "Vault aus"
        self.vault.schreibe_uebersicht(self.speicher.alle())
        return f"Vault: {self.vault.commit(nachricht)}"

    def _vault_alles(self, batch: dict, nachricht: str) -> None:
        for i in range(len(batch["eintraege"])):
            self._vault_eintrag(batch, i)
        self._vault_uebersicht(nachricht)
