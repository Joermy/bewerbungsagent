from __future__ import annotations

import mimetypes
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from .config import Smtp
from .profil import Profil


def dateiname(text: str) -> str:
    text = re.sub(r"[^\w\-. äöüÄÖÜß]", "", text).strip().replace(" ", "_")
    return re.sub(r"_+", "_", text)[:60] or "Datei"


def _anhaengen(msg: EmailMessage, pfad: Path, name: str | None = None) -> None:
    typ, _ = mimetypes.guess_type(str(pfad))
    haupt, _, unter = (typ or "application/octet-stream").partition("/")
    msg.add_attachment(pfad.read_bytes(), maintype=haupt, subtype=unter, filename=name or pfad.name)


def _grund(profil: Profil, absender_name: str, an: str, betreff: str, text: str, bcc: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((absender_name or profil.name, profil.email))
    msg["To"] = an
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = betreff
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=profil.email.split("@")[-1])
    msg.set_content(text)
    return msg


def bewerbungsmail(profil: Profil, eintrag: dict, anlagen: list[Path], absender_name: str = "",
                   bcc: str = "") -> EmailMessage:
    s = eintrag["stelle"]
    a = eintrag["anschreiben"]
    kern = a["betreff"].split(" - Ref.")[0].strip()
    worum = kern if kern.lower().startswith("bewerbung") else f"Bewerbung auf Ihre Anzeige „{s['titel']}“"
    herkunft = "" if s.get("quelle") == "manuell" else \
        f" (Referenznummer {s['refnr']}, Stellenanzeige in der Jobbörse der Bundesagentur für Arbeit)"
    text = (
        f"{a['anrede']}\n\n"
        f"anbei sende ich Ihnen meine {worum}{herkunft}.\n\n"
        f"Mein Anschreiben und meinen Lebenslauf finden Sie im Anhang als PDF. "
        f"Für Rückfragen erreichen Sie mich jederzeit"
        + (f" unter {profil.telefon}" if profil.telefon else "")
        + " oder per E-Mail.\n\n"
        f"Mit freundlichen Grüßen\n{profil.name}\n"
        + "\n".join(z for z in (profil.strasse, profil.plz_ort, profil.telefon, profil.portfolio) if z)
    )
    msg = _grund(profil, absender_name, s["email"], a["betreff"], text, bcc)
    _anhaengen(msg, Path(eintrag["pdf"]), f"Anschreiben_{dateiname(profil.name)}_{dateiname(s['firma'])}.pdf")
    for anlage in anlagen:
        _anhaengen(msg, anlage)
    return msg


def kanal_text(kanal: str | None, email: str = "") -> str:
    return {"portal": "online über das Bewerbungsportal", "post": "per Post",
            "persoenlich": "persönlich abgegeben"}.get(kanal or "email", f"per E-Mail an {email}")


def nachweismail(profil: Profil, an: str, eintraege: list[dict], nachweis: Path, datum: str,
                 absender_name: str = "", bcc: str = "") -> EmailMessage:
    def ref(s: dict) -> str:
        return "" if s.get("quelle") == "manuell" else f" (Ref. {s['refnr']})"

    zeilen = "\n".join(
        f"- {e['stelle']['firma']}, {e['stelle']['titel']}{ref(e['stelle'])}, "
        f"{kanal_text(e.get('kanal'), e['stelle'].get('email', ''))}"
        for e in eintraege
    )
    mit_pdf = [e for e in eintraege if e.get("pdf") and Path(e["pdf"]).is_file()]
    anzahl = f"{len(eintraege)} Bewerbung" + ("" if len(eintraege) == 1 else "en")
    anhang = "den Bewerbungsnachweis" + (" und die Anschreiben" if mit_pdf else "") + " als PDF"
    text = (
        "Sehr geehrte Damen und Herren,\n\n"
        f"zur Dokumentation meiner Eigenbemühungen sende ich Ihnen meine {anzahl} vom {datum}:\n\n{zeilen}\n\n"
        f"Im Anhang finden Sie {anhang}.\n\n"
        f"Mit freundlichen Grüßen\n{profil.name}"
    )
    msg = _grund(profil, absender_name, an, f"Bewerbungsnachweis {profil.name} - {anzahl} vom {datum}", text, bcc)
    _anhaengen(msg, nachweis)
    for e in mit_pdf:
        _anhaengen(msg, Path(e["pdf"]), f"Anschreiben_{dateiname(e['stelle']['firma'])}.pdf")
    return msg


class Versand:

    def __init__(self, smtp: Smtp):
        self.smtp = smtp
        self._verbindung: smtplib.SMTP | None = None

    def __enter__(self):
        s = self.smtp
        if s.port == 465:
            self._verbindung = smtplib.SMTP_SSL(s.host, s.port, context=ssl.create_default_context(), timeout=60)
        else:
            self._verbindung = smtplib.SMTP(s.host, s.port, timeout=60)
            if s.port == 587:
                self._verbindung.starttls(context=ssl.create_default_context())
        if s.user and s.password:
            self._verbindung.login(s.user, s.password)
        return self

    def schicke(self, msg: EmailMessage) -> None:
        assert self._verbindung is not None
        self._verbindung.send_message(msg)

    def __exit__(self, *_):
        if self._verbindung is not None:
            try:
                self._verbindung.quit()
            except smtplib.SMTPException:
                pass
