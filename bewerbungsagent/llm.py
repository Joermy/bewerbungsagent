from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile

import httpx

from .config import Config

STANDARD_URLS = {
    "lmstudio": "http://localhost:1234/v1",
    "ollama": "http://localhost:11434/v1",
}

_DENKEN = re.compile(r"<think>.*?</think>", re.S)


class LLMFehler(RuntimeError):
    pass


class KeinModell(LLMFehler):
    pass


def bereinige(text: str) -> str:
    text = _DENKEN.sub("", text)
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    text = text.strip()
    zaun = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return zaun.group(1) if zaun else text


def json_aus(text: str) -> dict:
    text = bereinige(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    ende = text.rfind("}")
    if start == -1 or ende <= start:
        raise LLMFehler(f"Keine JSON-Antwort: {text[:200]!r}")
    try:
        return json.loads(text[start : ende + 1])
    except json.JSONDecodeError as fehler:
        raise LLMFehler(f"Kaputtes JSON vom Modell: {fehler}") from fehler


class LLM:
    def __init__(self, cfg: Config, client: httpx.Client | None = None):
        self.cfg = cfg
        self.backend = cfg.llm.backend.lower()
        self.client = client or httpx.Client(timeout=cfg.llm.timeout_s)
        self._modell = cfg.llm.modell


    def frage(self, system: str, nutzer: str) -> str:
        if self.backend == "keins":
            raise KeinModell("llm.backend = keins")
        if self.backend == "claude-cli":
            return bereinige(self._claude(system, nutzer))
        if self.backend in ("lmstudio", "ollama", "openai"):
            return bereinige(self._openai(system, nutzer))
        raise LLMFehler(f"Unbekanntes llm.backend: {self.backend}")

    def frage_json(self, system: str, nutzer: str) -> dict:
        return json_aus(self.frage(system, nutzer))

    def bereit(self) -> tuple[bool, str]:
        if self.backend == "keins":
            return True, "kein Modell - Texte kommen ueber MCP"
        if self.backend == "claude-cli":
            pfad = shutil.which("claude")
            return (bool(pfad), pfad or "claude nicht auf PATH")
        try:
            antwort = self.client.get(f"{self._basis()}/models", headers=self._kopf(), timeout=5)
            antwort.raise_for_status()
            ids = [m.get("id") for m in antwort.json().get("data", [])]
            return True, f"{self._basis()} - Modelle: {', '.join(ids) or 'keins geladen'}"
        except httpx.HTTPError as fehler:
            return False, f"{self._basis()} nicht erreichbar: {fehler}"


    def _basis(self) -> str:
        return (self.cfg.llm.basis_url or STANDARD_URLS.get(self.backend, "")).rstrip("/")

    def _kopf(self) -> dict:
        return {"Authorization": f"Bearer {self.cfg.llm_api_key}"} if self.cfg.llm_api_key else {}

    def _modellname(self) -> str:
        if self._modell:
            return self._modell
        try:
            antwort = self.client.get(f"{self._basis()}/models", headers=self._kopf())
            antwort.raise_for_status()
        except httpx.HTTPError as fehler:
            raise LLMFehler(f"{self._basis()} nicht erreichbar: {fehler}") from fehler
        ids = [m["id"] for m in antwort.json().get("data") or [] if "embed" not in m.get("id", "").lower()]
        if not ids:
            raise LLMFehler(f"Kein Chat-Modell unter {self._basis()} - in LM Studio eins laden oder llm.modell setzen.")
        self._modell = ids[0]
        return self._modell

    def _openai(self, system: str, nutzer: str) -> str:
        nutzlast = {
            "model": self._modellname(),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": nutzer},
            ],
            "temperature": self.cfg.llm.temperatur,
        }
        try:
            antwort = self.client.post(f"{self._basis()}/chat/completions", json=nutzlast, headers=self._kopf())
            antwort.raise_for_status()
        except httpx.HTTPError as fehler:
            raise LLMFehler(f"{self._basis()}: {fehler}") from fehler
        return antwort.json()["choices"][0]["message"]["content"] or ""

    def _claude(self, system: str, nutzer: str) -> str:
        pfad = shutil.which("claude")
        if not pfad:
            raise LLMFehler("claude nicht auf PATH")
        befehl = [
            pfad, "-p",
            "--output-format", "text",
            "--tools", "",
            "--restricted",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--system-prompt", system,
        ]
        if self.cfg.llm.modell:
            befehl += ["--model", self.cfg.llm.modell]
        with tempfile.TemporaryDirectory() as leer:
            lauf = subprocess.run(
                befehl, input=nutzer, capture_output=True, text=True, encoding="utf-8",
                cwd=leer, timeout=self.cfg.llm.timeout_s,
            )
        if lauf.returncode != 0:
            meldung = (lauf.stderr.strip() or lauf.stdout.strip())[:300]
            if "Not logged in" in meldung:
                meldung += " - einmal im Terminal 'claude' starten und /login ausfuehren"
            raise LLMFehler(f"claude -p Exit {lauf.returncode}: {meldung}")
        return lauf.stdout
