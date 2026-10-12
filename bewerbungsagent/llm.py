from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

import httpx

from .config import Config
from . import modellcfg as mc
from .schemata import JE_AUFGABE

STANDARD_URLS = {
    "lmstudio": "http://localhost:1234/v1",
    "ollama": "http://localhost:11434/v1",
    "anthropic": "https://api.anthropic.com/v1",
}
ANTHROPIC_MODELL = "claude-sonnet-5-5"
BACKENDS = {
    "lmstudio": "LM Studio (lokal)",
    "ollama": "Ollama (lokal)",
    "openai": "OpenAI-kompatibler Server (llama.cpp, vLLM, Jan, ...)",
    "claude-cli": "Claude über die Claude-Code-CLI (eigenes Abo)",
    "anthropic": "Claude über die Anthropic-API (API-Schlüssel)",
    "keins": "kein Modell - Texte kommen über MCP von einem Agenten",
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


@dataclass
class Messung:
    aufgabe: str = ""
    sekunden: float = 0.0
    tokens_ein: int | None = None
    tokens_aus: int | None = None
    modell: str = ""
    strukturiert: bool = False

    @property
    def tokens_pro_s(self) -> float | None:
        if self.tokens_aus and self.sekunden > 0:
            return round(self.tokens_aus / self.sekunden, 1)
        return None

    def als_dict(self) -> dict:
        return {"aufgabe": self.aufgabe, "sekunden": round(self.sekunden, 2), "tokens_ein": self.tokens_ein,
                "tokens_aus": self.tokens_aus, "tokens_pro_s": self.tokens_pro_s, "modell": self.modell,
                "strukturiert": self.strukturiert}


@dataclass
class _Anfrage:
    system: str
    nutzer: str
    einstellung: mc.Einstellung
    schema: dict | None = None
    beispiele: list[tuple[str, str]] = field(default_factory=list)

    def nachrichten(self) -> list[dict]:
        m = [{"role": "system", "content": self.system}]
        for frage, antwort in self.beispiele:
            m += [{"role": "user", "content": frage}, {"role": "assistant", "content": antwort}]
        m.append({"role": "user", "content": self.nutzer})
        return m


class LLM:
    def __init__(self, cfg: Config, client: httpx.Client | None = None, modell: mc.Modellcfg | None = None):
        self.cfg = cfg
        self.backend = cfg.llm.backend.lower()
        self.client = client or httpx.Client(timeout=cfg.llm.timeout_s)
        self._modell = cfg.llm.modell
        self.mcfg = modell or mc.lade(cfg.wurzel)
        self.letzte: Messung | None = None
        self._ohne_schema = False

    # ------------------------------------------------------------ Eigenschaften

    @property
    def mehrstufig(self) -> bool:
        if self.backend in ("claude-cli", "anthropic"):
            return False
        return self.mcfg.basis().mehrstufig

    def einstellung(self, aufgabe: str | None = None) -> mc.Einstellung:
        e = self.mcfg.fuer(aufgabe)
        # Ohne modell.yaml gilt fuer Schreibaufgaben weiter llm.temperatur aus config.yaml
        if not (self.cfg.wurzel / "modell.yaml").exists() and aufgabe not in mc.AUFGABEN_STANDARD:
            e.temperatur = self.cfg.llm.temperatur
        return e

    def prompt(self, aufgabe: str, ersatz: str = "") -> str:
        try:
            return self.mcfg.prompt(aufgabe)
        except FileNotFoundError:
            return ersatz

    # ------------------------------------------------------------ Fragen

    def frage(self, system: str, nutzer: str, aufgabe: str | None = None, schema: dict | None = None,
              beispiele: list[tuple[str, str]] | None = None) -> str:
        if self.backend == "keins":
            raise KeinModell("llm.backend = keins")
        anfrage = _Anfrage(system, nutzer, self.einstellung(aufgabe), schema, beispiele or [])
        start = time.monotonic()
        self.letzte = Messung(aufgabe=aufgabe or "", strukturiert=bool(schema and anfrage.einstellung.strukturiert))
        if self.backend == "claude-cli":
            text = self._claude(anfrage)
        elif self.backend == "anthropic":
            text = self._anthropic(anfrage)
        elif self.backend == "ollama":
            text = self._ollama(anfrage)
        elif self.backend in ("lmstudio", "openai"):
            text = self._openai(anfrage)
        else:
            raise LLMFehler(f"Unbekanntes llm.backend: {self.backend}")
        self.letzte.sekunden = time.monotonic() - start
        return bereinige(text)

    def frage_json(self, system: str, nutzer: str, aufgabe: str | None = None, schema: dict | None = None,
                   beispiele: list[tuple[str, str]] | None = None) -> dict:
        schema = schema or (JE_AUFGABE.get(aufgabe) if aufgabe else None)
        text = self.frage(system, nutzer, aufgabe, schema, beispiele)
        try:
            return json_aus(text)
        except LLMFehler:
            # Ein Versuch mit klarer Bitte um reines JSON - hilft kleinen Modellen ohne Grammatik
            reparatur = nutzer + "\n\nWICHTIG: Antworte ausschliesslich mit gueltigem JSON, ohne Text davor oder danach."
            return json_aus(self.frage(system, reparatur, aufgabe, schema, beispiele))

    def bereit(self) -> tuple[bool, str]:
        if self.backend == "keins":
            return True, "kein Modell - Texte kommen ueber MCP"
        if self.backend == "claude-cli":
            pfad = shutil.which("claude")
            return (bool(pfad), pfad or "claude nicht auf PATH")
        if self.backend == "anthropic":
            if not self.cfg.llm_api_key:
                return False, "ANTHROPIC_API_KEY (oder LLM_API_KEY) in .env fehlt"
            return True, f"Anthropic-API, Modell {self.cfg.llm.modell or ANTHROPIC_MODELL}"
        try:
            ids = self.modelle()
            return True, f"{self._basis()} - Modelle: {', '.join(ids) or 'keins geladen'}"
        except LLMFehler as fehler:
            return False, str(fehler)

    def modelle(self) -> list[str]:
        if self.backend in ("claude-cli", "keins"):
            return []
        if self.backend == "anthropic":
            try:
                antwort = self.client.get(f"{self._basis()}/models", headers=self._anthropic_kopf(), timeout=8)
                antwort.raise_for_status()
            except httpx.HTTPError as fehler:
                raise LLMFehler(f"Anthropic-API: {fehler}") from fehler
            return [m.get("id") for m in antwort.json().get("data", []) if m.get("id")]
        try:
            antwort = self.client.get(f"{self._basis()}/models", headers=self._kopf(), timeout=5)
            antwort.raise_for_status()
        except httpx.HTTPError as fehler:
            raise LLMFehler(f"{self._basis()} nicht erreichbar: {fehler}") from fehler
        return [m.get("id") for m in antwort.json().get("data", []) if m.get("id")]

    # ------------------------------------------------------------ Backends

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

    def _openai(self, a: _Anfrage) -> str:
        e = a.einstellung
        nutzlast: dict = {
            "model": self._modellname(),
            "messages": a.nachrichten(),
            "temperature": e.temperatur,
            "top_p": e.top_p,
            "max_tokens": e.max_tokens,
        }
        if e.seed is not None:
            nutzlast["seed"] = e.seed
        if self.backend == "lmstudio":
            nutzlast["top_k"] = e.top_k
            nutzlast["repeat_penalty"] = e.wiederholung
        if a.schema and e.strukturiert and not self._ohne_schema:
            nutzlast["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "antwort", "strict": True, "schema": a.schema}}
        self.letzte.modell = nutzlast["model"]
        try:
            antwort = self.client.post(f"{self._basis()}/chat/completions", json=nutzlast, headers=self._kopf())
            if antwort.status_code == 400 and "response_format" in nutzlast:
                # Server oder Modell kann kein Schema - einmal ohne versuchen und merken
                self._ohne_schema = True
                self.letzte.strukturiert = False
                nutzlast.pop("response_format")
                antwort = self.client.post(f"{self._basis()}/chat/completions", json=nutzlast, headers=self._kopf())
            antwort.raise_for_status()
        except httpx.HTTPError as fehler:
            raise LLMFehler(f"{self._basis()}: {fehler}") from fehler
        daten = antwort.json()
        nutzung = daten.get("usage") or {}
        self.letzte.tokens_ein = nutzung.get("prompt_tokens")
        self.letzte.tokens_aus = nutzung.get("completion_tokens")
        return daten["choices"][0]["message"]["content"] or ""

    def _ollama(self, a: _Anfrage) -> str:
        """Ollamas eigene API: nur hier laesst sich num_ctx setzen. Ohne num_ctx schneidet
        Ollama lange Prompts stillschweigend auf die Standardlaenge ab."""
        e = a.einstellung
        basis = self._basis()
        nativ = basis[:-3] if basis.endswith("/v1") else basis
        optionen = {"temperature": e.temperatur, "top_p": e.top_p, "top_k": e.top_k,
                    "repeat_penalty": e.wiederholung, "num_ctx": e.kontext, "num_predict": e.max_tokens}
        if e.seed is not None:
            optionen["seed"] = e.seed
        nutzlast: dict = {"model": self._modellname(), "messages": a.nachrichten(), "stream": False,
                          "options": optionen}
        if a.schema and e.strukturiert:
            nutzlast["format"] = a.schema
        self.letzte.modell = nutzlast["model"]
        try:
            antwort = self.client.post(f"{nativ}/api/chat", json=nutzlast, headers=self._kopf())
            antwort.raise_for_status()
        except httpx.HTTPError as fehler:
            raise LLMFehler(f"{nativ}: {fehler}") from fehler
        daten = antwort.json()
        self.letzte.tokens_ein = daten.get("prompt_eval_count")
        self.letzte.tokens_aus = daten.get("eval_count")
        return (daten.get("message") or {}).get("content") or ""

    def _anthropic_kopf(self) -> dict:
        return {"x-api-key": self.cfg.llm_api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}

    def _anthropic(self, a: _Anfrage) -> str:
        """Messages-API. Das Schema geht als Anweisung in den Systemprompt; grosse Modelle halten es ein."""
        if not self.cfg.llm_api_key:
            raise KeinModell("ANTHROPIC_API_KEY (oder LLM_API_KEY) in .env eintragen")
        e = a.einstellung
        system = a.system
        if a.schema:
            system += "\n\nAntworte nur mit JSON nach diesem Schema:\n" + json.dumps(a.schema, ensure_ascii=False)
        nachrichten = [m for m in a.nachrichten() if m["role"] != "system"]
        nutzlast = {"model": self.cfg.llm.modell or ANTHROPIC_MODELL, "system": system, "messages": nachrichten,
                    "max_tokens": max(e.max_tokens, 600), "temperature": min(e.temperatur, 1.0)}
        self.letzte.modell = nutzlast["model"]
        try:
            antwort = self.client.post(f"{self._basis()}/messages", json=nutzlast, headers=self._anthropic_kopf())
            antwort.raise_for_status()
        except httpx.HTTPError as fehler:
            raise LLMFehler(f"Anthropic-API: {fehler}") from fehler
        daten = antwort.json()
        nutzung = daten.get("usage") or {}
        self.letzte.tokens_ein = nutzung.get("input_tokens")
        self.letzte.tokens_aus = nutzung.get("output_tokens")
        return "".join(t.get("text", "") for t in daten.get("content") or [] if t.get("type") == "text")

    def _claude(self, a: _Anfrage) -> str:
        pfad = shutil.which("claude")
        if not pfad:
            raise LLMFehler("claude nicht auf PATH")
        system = a.system
        if a.schema:
            system += "\n\nAntworte nur mit JSON nach diesem Schema:\n" + json.dumps(a.schema, ensure_ascii=False)
        nutzer = a.nutzer
        if a.beispiele:
            nutzer = "\n\n".join(f"Beispiel-Eingabe:\n{f}\nBeispiel-Antwort:\n{r}" for f, r in a.beispiele) + \
                     "\n\n" + nutzer
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
        self.letzte.modell = self.cfg.llm.modell or "claude"
        return lauf.stdout
