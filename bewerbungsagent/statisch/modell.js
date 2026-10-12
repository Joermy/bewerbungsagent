"use strict";
// Modell, Voreinstellungen, Systemprompts, Prompt-Labor und Agenten-Anbindung

const MOD = { d: null, verbindung: null, voreinstellung: "klein", eigene: {}, aufgaben: {}, prompt: null };

const FELD_INFO = {
  kontext: ["Kontext (Tokens)", "num_ctx bei Ollama. In LM Studio beim Laden des Modells einstellen."],
  temperatur: ["Temperatur", "Niedrig = verlässlich, hoch = abwechslungsreich. Für 8B-Modelle 0,3–0,5."],
  top_p: ["top_p", "Nucleus Sampling."],
  top_k: ["top_k", "Nur LM Studio und Ollama."],
  wiederholung: ["Wiederholungsstrafe", "repeat_penalty – gegen Schleifen bei kleinen Modellen, 1,05–1,15."],
  max_tokens: ["Max. Antwort (Tokens)", "Obergrenze der Antwortlänge."],
  seed: ["Seed", "Fester Wert = reproduzierbare Antworten. Leer = zufällig."],
  strukturiert: ["JSON-Schema erzwingen", "Grammatik im Server: das Modell kann nur gültiges JSON schreiben."],
  mehrstufig: ["Anschreiben in zwei Schritten", "Erst Anzeige auswerten, dann schreiben – deutlich besser bei 7–9B."],
  beispiele: ["Beispiele mitschicken", "Few-Shot-Beispiele im Prompt."],
  anzeige_zeichen: ["Anzeigentext (Zeichen)", "So viel der Anzeige geht ans Modell."],
  profil_zeichen: ["Profiltext (Zeichen)", "So viel des Profils geht ans Modell."],
};

const VOR_TEXT = {
  klein: ["Klein", "7–9B, z. B. Llama 3.1 8B, Hermes 3 8B, Qwen 2.5 7B"],
  mittel: ["Mittel", "12–14B, z. B. Qwen 2.5 14B, Mistral Nemo, Gemma 3 12B"],
  gross: ["Groß", "27B und mehr oder Claude"],
};

ansichten.modell = async function ladeModell() {
  const d = await api("/api/modell");
  MOD.d = d;
  MOD.verbindung = { ...d.verbindung };
  MOD.voreinstellung = d.voreinstellung;
  MOD.eigene = structuredClone(d.eigene_werte || {});
  MOD.aufgaben = structuredClone(d.aufgaben_werte || {});
  MOD.prompt = MOD.prompt || d.prompts[0].aufgabe;
  zeichneVerbindung();
  zeichneVoreinstellung();
  zeichneAufgaben();
  zeichnePrompts();
  zeichneLabor();
  zeichneAgenten();
};

function zeichneVerbindung() {
  const d = MOD.d;
  const v = MOD.verbindung;
  const backend = el("select", {}, ...Object.entries(d.backends).map(([k, t]) => el("option", { value: k, text: t })));
  backend.value = v.backend;
  backend.addEventListener("change", () => { v.backend = backend.value; zeichneVerbindung(); });
  const liste = el("datalist", { id: "modellListe" }, ...d.modelle.map((m) => el("option", { value: m })));
  const modell = el("input", { list: "modellListe", value: v.modell || "", placeholder: d.modelle[0] ? `leer = ${d.modelle[0]}` : "leer = erstes geladenes Modell" });
  modell.addEventListener("input", () => { v.modell = modell.value; });
  const url = el("input", { value: v.basis_url || "", placeholder: d.verbindung.standard_url || "" });
  url.addEventListener("input", () => { v.basis_url = url.value; });
  const lokal = ["lmstudio", "ollama", "openai"].includes(v.backend);
  const hilfe = {
    lmstudio: "LM Studio: Modell laden, unter Developer den Server starten (Port 1234). Structured Output wird genutzt.",
    ollama: "Ollama: ollama pull llama3.1:8b – der Agent setzt num_ctx selbst, damit lange Anzeigen nicht abgeschnitten werden.",
    openai: "Jeder Server mit /v1/chat/completions: llama.cpp (llama-server), vLLM, Jan, LocalAI.",
    "claude-cli": "Nutzt dein Claude-Abo über die Claude-Code-CLI (claude muss im PATH liegen und angemeldet sein).",
    anthropic: "Anthropic-API mit Schlüssel in .env (ANTHROPIC_API_KEY). Modell leer = claude-sonnet-5-5.",
    keins: "Kein Modell: Suche und PDFs laufen, die Texte schreibt ein Agent über MCP (z. B. Claude Code oder Hermes).",
  }[v.backend];
  $("#verbindungKarte").replaceChildren(
    el("h3", { text: "Verbindung" }),
    el("div", { class: "status-zeile" }, el("span", { class: "lampe " + (d.bereit ? "an" : "aus") }), el("span", { text: d.info })),
    el("label", { class: "feld" }, el("span", { text: "Backend" }), backend),
    el("p", { class: "gedaempft klein", text: hilfe }),
    v.backend !== "keins" ? el("div", { class: "zwei" },
      el("label", { class: "feld" }, el("span", { text: "Modell" }), modell, liste),
      lokal || v.backend === "anthropic" ? el("label", { class: "feld" }, el("span", { text: "Server-Adresse" }), url) : el("span")) : null,
    el("p", { class: "gedaempft klein", text: "Gespeichert wird in modell.yaml – config.yaml bleibt unangetastet." }));
}

function wertFeld(name, wert, standard, fn) {
  const [titel, info] = FELD_INFO[name] || [name, ""];
  if (typeof standard === "boolean") {
    const c = el("input", { type: "checkbox" });
    c.checked = wert === undefined ? standard : !!wert;
    c.addEventListener("change", () => fn(c.checked));
    return el("label", { class: "haken wert", title: info }, c, " " + titel);
  }
  const i = el("input", { type: "number", step: name === "temperatur" || name === "top_p" || name === "wiederholung" ? "0.01" : "1",
    value: wert === undefined || wert === null ? "" : String(wert), placeholder: standard === null ? "zufällig" : String(standard) });
  i.addEventListener("input", () => fn(i.value === "" ? null : Number(i.value)));
  return el("label", { class: "feld", title: info }, el("span", { text: titel }), i);
}

function zeichneVoreinstellung() {
  const d = MOD.d;
  const karten = el("div", { class: "segment gross" }, ...Object.keys(d.voreinstellungen).map((k) => el("button", {
    class: MOD.voreinstellung === k ? "aktiv" : "", onclick: () => { MOD.voreinstellung = k; zeichneVoreinstellung(); },
  }, el("strong", { text: VOR_TEXT[k][0] }), el("small", { text: VOR_TEXT[k][1] }))));
  const name = MOD.voreinstellung;
  const standard = d.standard_werte[name];
  const eigene = MOD.eigene[name] || (MOD.eigene[name] = {});
  const setze = (f) => (v) => { if (v === null || v === "") delete eigene[f]; else eigene[f] = v; };
  const zahlen = d.felder.filter((f) => typeof standard[f] !== "boolean").map((f) => wertFeld(f, eigene[f], standard[f], setze(f)));
  const schalter = d.felder.filter((f) => typeof standard[f] === "boolean").map((f) => wertFeld(f, eigene[f], standard[f], setze(f)));
  $("#voreinstellungKarte").replaceChildren(
    el("h3", { text: "Voreinstellung" }), karten,
    el("p", { class: "gedaempft klein", text: "Leere Felder nehmen den Wert der Voreinstellung (grau). Eigene Werte gelten nur für diese Voreinstellung." }),
    el("div", { class: "werte-raster" }, ...zahlen),
    el("div", { class: "werte-schalter" }, ...schalter),
    el("button", { class: "knopf klein leise", text: "Eigene Werte dieser Voreinstellung löschen", onclick: () => { MOD.eigene[name] = {}; zeichneVoreinstellung(); } }));
}

function zeichneAufgaben() {
  const d = MOD.d;
  const basis = d.voreinstellungen[MOD.voreinstellung];
  const zeilen = Object.entries(d.aufgaben).filter(([k]) => k !== "agent").map(([k, text]) => {
    const eigen = MOD.aufgaben[k] || (MOD.aufgaben[k] = {});
    const std = { ...basis, ...(d.aufgaben_standard[k] || {}) };
    const zahl = (f) => {
      const i = el("input", { type: "number", step: f === "temperatur" ? "0.01" : "1", class: "schmal-zahl", value: eigen[f] ?? "", placeholder: String(std[f]) });
      i.addEventListener("input", () => { if (i.value === "") delete eigen[f]; else eigen[f] = Number(i.value); });
      return i;
    };
    return [el("div", {}, el("code", { text: k }), el("small", { class: "gedaempft block", text })), zahl("temperatur"), zahl("max_tokens")];
  });
  const t = el("table", { class: "tabelle" });
  $("#aufgabenKarte").replaceChildren(el("h3", { text: "Pro Aufgabe" }),
    el("p", { class: "gedaempft klein", text: "Bewerten und Auswerten brauchen eine niedrige Temperatur, Schreiben etwas mehr. Leer = Standard (grau)." }), t);
  tabelle(t, ["Aufgabe", "Temperatur", "Max. Tokens"], zeilen, "");
}

$("#modellSpeichern").addEventListener("click", async () => {
  try {
    const d = await api("/api/modell", { voreinstellung: MOD.voreinstellung, voreinstellungen: MOD.eigene, aufgaben: MOD.aufgaben, verbindung: MOD.verbindung });
    MOD.d = d;
    zeichneVerbindung();
    $("#modellSpeichern").textContent = "Gespeichert ✓";
    setTimeout(() => { $("#modellSpeichern").textContent = "Einstellungen speichern"; }, 1800);
  } catch (err) { hinweis(err.message); }
});

// ---------------------------------------------------------------- Systemprompts

function zeichnePrompts() {
  const d = MOD.d;
  $("#promptListe").replaceChildren(...d.prompts.map((p) => el("li", {}, el("button", {
    class: p.aufgabe === MOD.prompt ? "aktiv" : "", onclick: () => { MOD.prompt = p.aufgabe; zeichnePrompts(); },
  }, el("span", { text: p.aufgabe }), p.eigen ? el("small", { class: "marke-eigen", text: "eigen" }) : null))));
  const p = d.prompts.find((x) => x.aufgabe === MOD.prompt);
  const text = el("textarea", { class: "code", rows: "18", spellcheck: "false" });
  text.value = p.text;
  const klein = ["klein", "mittel"].includes(MOD.voreinstellung);
  $("#promptEditor").replaceChildren(
    el("div", { class: "prompt-kopf" }, el("div", {}, el("h3", { text: p.aufgabe }), el("p", { class: "gedaempft klein", text: p.beschreibung })),
      el("span", { class: "pille " + (p.eigen ? "entwurf" : ""), text: p.eigen ? "eigene Fassung" : "Standard" })),
    text,
    el("p", { class: "gedaempft klein", text: (klein ? "Für kleine und mittlere Modelle gilt die .klein-Fassung, falls es eine gibt. " : "") +
      "Gespeichert wird in profil/prompts/ – das Paket bleibt unverändert. Kleine Modelle mögen kurze Sätze, nummerierte Regeln und ein JSON-Beispiel am Ende." }),
    el("div", { class: "aktionen" },
      el("button", { class: "knopf primaer", text: "Prompt speichern", onclick: async () => {
        try { MOD.d = await api("/api/modell/prompt", { aufgabe: p.aufgabe, text: text.value }); zeichnePrompts(); } catch (err) { hinweis(err.message); }
      } }),
      el("button", { class: "knopf leise", text: "Standard wiederherstellen", onclick: async () => {
        if (!confirm("Eigene Fassung löschen und den Standard nehmen?")) return;
        try { MOD.d = await api("/api/modell/prompt", { aufgabe: p.aufgabe, zuruecksetzen: true }); zeichnePrompts(); } catch (err) { hinweis(err.message); }
      } }),
      el("button", { class: "knopf leise", text: "Im Labor testen", onclick: () => {
        $("#laborAufgabe").value = p.aufgabe; $("#laborSystem").value = text.value; $("#laborKarte").scrollIntoView({ behavior: "smooth" });
      } })));
}

// ---------------------------------------------------------------- Prompt-Labor

function zeichneLabor() {
  const d = MOD.d;
  const aufgabe = el("select", { id: "laborAufgabe" },
    el("option", { value: "kette", text: "Ganzes Anschreiben (alle Schritte wie im Lauf)" }),
    ...Object.entries(d.aufgaben).map(([k, t]) => el("option", { value: k, text: `${k} – ${t}` })));
  aufgabe.value = "kette";
  const system = el("textarea", { id: "laborSystem", class: "code", rows: "6", placeholder: "leer = aktueller Systemprompt der Aufgabe", spellcheck: "false" });
  const nutzer = el("textarea", { id: "laborNutzer", class: "code", rows: "10", placeholder: "Eingabe – oder „Beispiel laden“", spellcheck: "false" });
  const temp = el("input", { type: "number", step: "0.05", class: "schmal-zahl", placeholder: "Std." });
  const schema = el("input", { type: "checkbox" });
  schema.checked = true;
  const ausgabe = el("div", { class: "labor-ausgabe" });
  aufgabe.addEventListener("change", () => {
    system.disabled = aufgabe.value === "kette";
    system.value = "";
    nutzer.disabled = aufgabe.value === "kette";
  });
  system.disabled = nutzer.disabled = true;
  const beispiel = el("button", { class: "knopf klein", text: "Beispiel laden", onclick: async () => {
    try {
      const b = await api("/api/modell/beispiel", { aufgabe: aufgabe.value });
      nutzer.value = b.nutzer;
      const p = d.prompts.find((x) => x.aufgabe === aufgabe.value);
      if (p && !system.value) system.value = p.text;
    } catch (err) { hinweis(err.message); }
  } });
  const los = el("button", { class: "knopf primaer", text: "Ausführen", onclick: async () => {
    ausgabe.replaceChildren(el("p", { class: "gedaempft", text: "Modell arbeitet …" }));
    const daten = { aufgabe: aufgabe.value, system: system.value, nutzer: nutzer.value, schema: schema.checked };
    if (temp.value !== "") daten.einstellung = { temperatur: Number(temp.value) };
    try {
      const r = await auftragErgebnis("/api/modell/test", daten);
      const m = r.messung || {};
      const zahlen = [
        m.sekunden !== undefined ? `${m.sekunden} s` : "",
        m.tokens_aus ? `${m.tokens_aus} Tokens` : "",
        m.tokens_pro_s ? `${m.tokens_pro_s} Tokens/s` : "",
        m.modell || "",
        m.strukturiert ? "Schema erzwungen" : "",
      ].filter(Boolean);
      const teile = [el("div", { class: "messwerte" }, ...zahlen.map((z) => el("span", { class: "chip", text: z })))];
      if (m.schritte) teile.push(el("p", { class: "gedaempft klein", text: m.schritte.map((s) => `${s.aufgabe}: ${s.sekunden} s${s.tokens_pro_s ? `, ${s.tokens_pro_s} T/s` : ""}`).join(" · ") }));
      if (r.maengel) teile.push(el("p", { class: r.maengel.length ? "warnung" : "gut-text", text: r.maengel.length ? "Prüfung: " + r.maengel.join(", ") : "Prüfung bestanden: keine Platzhalter, Floskeln oder unbelegten Angaben." }));
      teile.push(el("pre", { class: "antwort", text: huebsch(r.antwort) }));
      ausgabe.replaceChildren(...teile);
    } catch (err) {
      ausgabe.replaceChildren(el("p", { class: "warnung", text: err.message }));
    }
  } });
  $("#laborKarte").replaceChildren(
    el("p", { class: "gedaempft", text: "Prompt und Werte ausprobieren, ohne einen Lauf zu starten. Das Beispiel nimmt eine Stelle aus deinem letzten Lauf – oder eine Musteranzeige." }),
    el("div", { class: "labor-raster" },
      el("div", {},
        el("label", { class: "feld" }, el("span", { text: "Aufgabe" }), aufgabe),
        el("label", { class: "feld" }, el("span", { text: "Systemprompt für diesen Test" }), system),
        el("label", { class: "feld" }, el("span", { text: "Eingabe" }), nutzer),
        el("div", { class: "aktionen" }, beispiel,
          el("label", { class: "feld inline" }, el("span", { text: "Temperatur" }), temp),
          el("label", { class: "haken" }, schema, " JSON-Schema"), los)),
      ausgabe));
}

function huebsch(text) {
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch (e) { return text; }
}

// ---------------------------------------------------------------- Agenten

async function zeichneAgenten() {
  const a = await api("/api/agenten");
  const block = (titel, text, unter) => {
    const pre = el("pre", { class: "code-block", text });
    const kopieren = el("button", { class: "knopf klein leise", text: "Kopieren", onclick: async () => {
      try { await navigator.clipboard.writeText(text); kopieren.textContent = "Kopiert ✓"; } catch (e) { kopieren.textContent = "Bitte markieren"; }
      setTimeout(() => { kopieren.textContent = "Kopieren"; }, 1500);
    } });
    return el("div", { class: "agent-block" }, el("div", { class: "agent-kopf" }, el("strong", { text: titel }), kopieren), unter ? el("p", { class: "gedaempft klein", text: unter }) : null, pre);
  };
  const skillKnopf = el("button", { class: "knopf klein primaer", text: a.hermes_skill_da ? "Hermes-Skill aktualisieren" : "Hermes-Skill installieren", onclick: async () => {
    try { const r = await api("/api/agenten/hermes-skill", {}); skillKnopf.textContent = "Installiert ✓"; skillKnopf.title = r.pfad; } catch (err) { hinweis(err.message); }
  } });
  $("#agentenKarte").replaceChildren(
    el("p", { class: "gedaempft", text: "Der Bewerbungsagent ist auch ein MCP-Server. Damit kann ein Agent – Hermes Agent mit einem lokalen Modell, Claude Code oder Claude Desktop – suchen, Anschreiben setzen und den Lebenslauf pflegen. Senden bleibt in der App." }),
    el("div", { class: "raster-2" },
      el("div", {}, block("Hermes Agent – ~/.hermes/config.yaml", a.hermes_config, "Danach in Hermes: /reload-mcp. Hermes braucht ein Modell mit mindestens 64k Kontext."),
        el("div", { class: "aktionen" }, skillKnopf, el("span", { class: "gedaempft klein", text: a.hermes_skill_pfad }))),
      el("div", {}, block("Claude Code", a.claude_code), block("Claude Desktop – claude_desktop_config.json", a.claude_desktop))),
    block("Systemprompt für Agenten (Aufgabe „agent“ oben bearbeitbar)", a.agent_prompt));
}
