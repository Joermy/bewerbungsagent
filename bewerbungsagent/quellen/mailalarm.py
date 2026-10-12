"""Jobalarme aus dem eigenen Postfach lesen (IMAP).

Indeed, StepStone, LinkedIn, XING und die Arbeitsagentur schicken auf Wunsch taeglich
passende Anzeigen per Mail. Statt die Portale abzugrasen, liest dieses Modul diese
Mails: Titel, Firma, Ort und Link zur Anzeige. Zugang in .env:
IMAP_HOST, IMAP_USER, IMAP_PASSWORD (bei Gmail ein App-Passwort).
Es wird nur gelesen, nichts geloescht oder als gelesen markiert (BODY.PEEK).
"""
from __future__ import annotations

import email
import hashlib
import imaplib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from email.header import decode_header, make_header
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

from ..stelle import Stelle
from .gemeinsam import QuellenFehler, baue

ABSENDER = {
    "indeed": ("indeed.com", "indeedemail.com", "indeed.de"),
    "stepstone": ("stepstone.de", "stepstone.com"),
    "linkedin": ("linkedin.com",),
    "xing": ("xing.com",),
    "arbeitsagentur": ("arbeitsagentur.de",),
    "monster": ("monster.de", "monster.com"),
    "glassdoor": ("glassdoor.com", "glassdoor.de"),
}

# Links, die auf eine einzelne Anzeige zeigen
JOBLINK = re.compile(
    r"indeed\.[a-z.]+/(rc/clk|viewjob|pagead/clk|m/viewjob|jobs\?jk=|.*[?&]jk=)|"
    r"stepstone\.[a-z]+/(stellenangebote--|job/|.*/stellenangebot)|"
    r"linkedin\.com/(comm/)?jobs/view/|xing\.com/(m/)?jobs/|"
    r"arbeitsagentur\.de/jobsuche/jobdetail/|monster\.[a-z.]+/(stellenangebot|job-openings|jobs/)|"
    r"glassdoor\.[a-z.]+/(partner/jobListing|job-listing)", re.I)

_UNSINN = re.compile(r"^(jetzt bewerben|bewerben|ansehen|mehr anzeigen|alle jobs|abmelden|einstellungen|"
                     r"view job|apply|see all|mehr|details|hier|zur anzeige|job ansehen)\b", re.I)


@dataclass
class Fund:
    titel: str
    url: str
    portal: str
    kontext: list[str]


class _Links(HTMLParser):
    """Sammelt Links mit ihrem Text und die Textzeilen danach (Firma, Ort)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.zeilen: list[tuple[str, str | None]] = []  # (Text, Link oder None)
        self._href: str | None = None
        self._text: list[str] = []
        self._still = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._still += 1
        elif tag == "a":
            self._fluss()
            self._href = dict(attrs).get("href") or ""
        elif tag in ("br", "p", "div", "td", "tr", "li", "h1", "h2", "h3", "table"):
            self._fluss()

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head") and self._still:
            self._still -= 1
        elif tag == "a":
            self._fluss()
            self._href = None
        elif tag in ("p", "div", "td", "li", "h1", "h2", "h3"):
            self._fluss()

    def handle_data(self, data):
        if not self._still:
            self._text.append(data)

    def _fluss(self):
        text = re.sub(r"\s+", " ", "".join(self._text)).strip()
        self._text = []
        if text:
            self.zeilen.append((text, self._href))


def _ziel(url: str) -> str:
    """Tracking-Weiterleitungen auspacken, soweit das Ziel im Link steht."""
    try:
        q = parse_qs(urlparse(url).query)
    except ValueError:
        return url
    for k in ("url", "u", "dest", "target", "redirect"):
        if q.get(k) and q[k][0].startswith("http"):
            return unquote(q[k][0])
    return url


def funde_aus_html(seite: str, portal: str) -> list[Fund]:
    leser = _Links()
    leser.feed(seite)
    leser._fluss()
    funde: list[Fund] = []
    gesehen: set[str] = set()
    for i, (text, href) in enumerate(leser.zeilen):
        if not href:
            continue
        ziel = _ziel(href)
        if not (JOBLINK.search(ziel) or JOBLINK.search(href)):
            continue
        if _UNSINN.search(text) or not (6 <= len(text) <= 140):
            continue
        schluessel = text.lower()
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        kontext = [t for t, h in leser.zeilen[i + 1:i + 5] if not h or not JOBLINK.search(_ziel(h))][:3]
        funde.append(Fund(text, ziel, portal, kontext))
    return funde


def zu_stelle(f: Fund) -> Stelle:
    firma = f.kontext[0] if f.kontext else ""
    ort = f.kontext[1] if len(f.kontext) > 1 else ""
    if re.search(r"\d{5}|,|\b(remote|homeoffice)\b", firma, re.I) and not ort:
        firma, ort = "", firma
    kennung = hashlib.sha1(f"{f.titel}|{firma}".encode()).hexdigest()[:16]
    return baue(f"mail-{f.portal}", kennung, f.titel, firma, beschreibung="\n".join(f.kontext), url=f.url,
                ort=ort.split(",")[0][:60])


def _portal(absender: str) -> str | None:
    a = absender.lower()
    for name, domains in ABSENDER.items():
        if any(d in a for d in domains):
            return name
    return None


def _html_teil(nachricht: email.message.Message) -> str:
    for teil in nachricht.walk():
        if teil.get_content_type() == "text/html":
            roh = teil.get_payload(decode=True) or b""
            return roh.decode(teil.get_content_charset() or "utf-8", errors="replace")
    return ""


class Postfach:
    name = "Jobalarme (Mail)"

    def __init__(self, host: str, user: str, passwort: str, port: int = 993, ordner: str = "INBOX"):
        if not (host and user and passwort):
            raise QuellenFehler("Jobalarme: IMAP_HOST, IMAP_USER und IMAP_PASSWORD in .env eintragen")
        self.host, self.user, self.passwort, self.port, self.ordner = host, user, passwort, port, ordner

    def lies(self, tage: int = 10, max_mails: int = 60) -> list[Stelle]:
        seit = (date.today() - timedelta(days=tage)).strftime("%d-%b-%Y")
        try:
            verbindung = imaplib.IMAP4_SSL(self.host, self.port, timeout=40)
        except OSError as fehler:
            raise QuellenFehler(f"Postfach nicht erreichbar: {fehler}") from fehler
        stellen: list[Stelle] = []
        try:
            verbindung.login(self.user, self.passwort)
            verbindung.select(f'"{self.ordner}"', readonly=True)
            nummern: list[bytes] = []
            for domains in ABSENDER.values():
                for d in domains:
                    status, daten = verbindung.search(None, "SINCE", seit, "FROM", d)
                    if status == "OK" and daten and daten[0]:
                        nummern += daten[0].split()
            for nr in sorted(set(nummern), key=int, reverse=True)[:max_mails]:
                status, daten = verbindung.fetch(nr, "(BODY.PEEK[])")
                if status != "OK" or not daten or not isinstance(daten[0], tuple):
                    continue
                nachricht = email.message_from_bytes(daten[0][1])
                portal = _portal(str(make_header(decode_header(nachricht.get("From", "")))))
                if not portal:
                    continue
                for f in funde_aus_html(_html_teil(nachricht), portal):
                    stellen.append(zu_stelle(f))
        except imaplib.IMAP4.error as fehler:
            raise QuellenFehler(f"Anmeldung am Postfach fehlgeschlagen: {fehler}") from fehler
        finally:
            try:
                verbindung.logout()
            except Exception:
                pass
        return stellen
