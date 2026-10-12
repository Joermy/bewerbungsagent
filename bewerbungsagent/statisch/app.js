"use strict";

const TOKEN = document.querySelector('meta[name="token"]').content;
const $ = (sel, wurzel = document) => wurzel.querySelector(sel);
const $$ = (sel, wurzel = document) => [...wurzel.querySelectorAll(sel)];

const zustand = { batch: null, batchId: null, offen: new Set(), auftragLief: false };
// Weitere Ansichten (lebenslauf.js, quellen.js, modell.js) tragen sich hier ein
const ansichten = {};

async function api(pfad, daten) {
  const antwort = await fetch(pfad, {
    method: daten === undefined ? "GET" : "POST",
    headers: { "X-Token": TOKEN, "Content-Type": "application/json" },
    body: daten === undefined ? undefined : JSON.stringify(daten),
  });
  const json = await antwort.json().catch(() => ({}));
  if (!antwort.ok) throw new Error(json.fehler || `HTTP ${antwort.status}`);
  return json;
}

function datum(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("de-DE") + (iso.length > 10 ? " " + d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : "");
}

function el(tag, attrs = {}, ...kinder) {
  const knoten = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") knoten.textContent = v;
    else if (k.startsWith("on")) knoten.addEventListener(k.slice(2), v);
    else knoten.setAttribute(k, v);
  }
  knoten.append(...kinder.filter((k) => k !== null && k !== undefined));
  return knoten;
}

function hinweis(text) {
  const feld = $("#auftrag");
  feld.classList.remove("versteckt", "fertig");
  feld.classList.add("fehler");
  $("#auftragName").textContent = text;
  $("#auftragLog").textContent = "";
  $("#auftragZu").classList.remove("versteckt");
}

function zeige(ansicht) {
  $$(".reiter button").forEach((b) => b.classList.toggle("aktiv", b.dataset.ansicht === ansicht));
  $$("section.ansicht").forEach((s) => s.classList.toggle("versteckt", s.dataset.ansicht !== ansicht));
  $("#versandleiste").classList.toggle("versteckt", ansicht !== "lauf" || !zustand.batch);
  if (ansicht === "verlauf") ladeVerlauf();
  if (ansicht === "einrichtung") ladeStatus();
  if (ansicht === "haendisch") zeigeHaendisch();
  if (ansichten[ansicht]) ansichten[ansicht]().catch((err) => hinweis(err.message));
  try { sessionStorage.setItem("ansicht", ansicht); } catch (e) { /* egal */ }
}

async function ladeLaeufe(waehle) {
  const laeufe = await api("/api/batches");
  const liste = $("#laeufe");
  liste.replaceChildren();
  if (!laeufe.length) liste.append(el("li", { class: "gedaempft", text: "noch keine" }));
  for (const l of laeufe) {
    const knopf = el("button", { onclick: () => ladeBatch(l.id) },
      el("span", { text: datum(l.erstellt) }),
      el("small", { text: l.gesendet ? `${l.gesendet}/${l.anzahl} gesendet` : `${l.anzahl} Entwürfe` }));
    if (l.id === zustand.batchId) knopf.classList.add("aktiv");
    liste.append(el("li", {}, knopf));
  }
  const ziel = waehle || zustand.batchId || (laeufe[0] && laeufe[0].id);
  if (ziel) await ladeBatch(ziel);
}

async function ladeBatch(id) {
  zustand.batch = await api(`/api/batch/${encodeURIComponent(id)}`);
  if (zustand.batchId !== id) zustand.offen.clear();
  zustand.batchId = id;
  $$("#laeufe button").forEach((b, i) => b.classList.toggle("aktiv", b.firstChild.textContent === datum(zustand.batch.erstellt)));
  zeichneBatch();
}

function zeichneBatch() {
  const b = zustand.batch;
  const aktiv = b.eintraege.filter((e) => e.status !== "entfernt");
  $("#laufTitel").textContent = `Lauf vom ${datum(b.erstellt)}`;
  $("#laufInfo").textContent =
    `${aktiv.length} Bewerbungen · ${b.ohne_email.length} selbst bewerben · ${b.aussortiert} aussortiert` +
    (b.sachbearbeitung ? ` · Nachweis an Sachbearbeitung am ${datum(b.sachbearbeitung.zeit)}` : "");
  $("#verwerfen").classList.toggle("versteckt", b.status !== "offen");
  const karten = $("#karten");
  karten.replaceChildren();
  if (!b.eintraege.length) karten.append(el("div", { class: "leer", text: "Keine passenden Stellen mit E-Mail-Adresse gefunden. Suchbegriffe oder Umkreis im Profil erweitern." }));
  b.eintraege.forEach((e, i) => karten.append(karte(e, i)));
  zeichneVersandleiste();
}

function karte(e, i) {
  const k = $("#kartenVorlage").content.firstElementChild.cloneNode(true);
  const s = e.stelle;
  const a = e.anschreiben;
  if (e.status === "entfernt") k.classList.add("entfernt");
  const punkte = $(".punkte", k);
  punkte.textContent = s.punkte;
  punkte.classList.add(s.punkte >= 70 ? "hoch" : s.punkte >= 45 ? "mittel" : "niedrig");
  $("h2", k).textContent = s.titel;
  $(".firma", k).textContent = `${s.firma} · ${[s.plz, s.ort].filter(Boolean).join(" ")}`;
  const pille = $(".pille", k);
  const stand = e.status === "entwurf" && !a ? "ohne-text" : e.status;
  pille.textContent = { "ohne-text": "Text fehlt", entwurf: "Entwurf", gesendet: e.rueckmeldung || "gesendet", entfernt: "entfernt", fehler: "Fehler" }[stand] || stand;
  pille.classList.add(stand);

  const inhalt = $(".karte-inhalt", k);
  const auf = () => {
    const zu = inhalt.classList.toggle("versteckt");
    zu ? zustand.offen.delete(i) : zustand.offen.add(i);
    $(".aufklappen", k).textContent = zu ? "Öffnen" : "Schließen";
    if (!zu && !$("iframe", k).src) kartenVorschau(k, i, e.anschreiben ? "anschreiben" : "lebenslauf");
  };
  $(".karte-kopf", k).addEventListener("click", (ev) => { if (!ev.target.closest("a")) auf(); });

  $(".begruendung", k).textContent = s.begruendung ? `Passung ${s.punkte}/100 – ${s.begruendung}` : "";
  const fakten = $(".fakten", k);
  const fakt = (dt, dd) => dd && fakten.append(el("dt", { text: dt }), el("dd", { text: dd }));
  fakt("Art", s.art === "ausbildung" ? `Ausbildung${s.beginn ? " ab " + datum(s.beginn) : ""}` : "");
  fakt("Abschluss verlangt", (s.abschluss_gefordert || "").replace(/_/g, " ").toLowerCase());
  fakt("An", s.email);
  fakt("Hinweis", s.zeugnis_verlangt ? "Anzeige verlangt Schulzeugnis – angehängt ist nur der Lebenslauf" : "");
  fakt("Ansprechpartner", s.ansprechpartner);
  fakt("Referenz", s.refnr);
  fakt("Veröffentlicht", datum(s.veroeffentlicht));
  fakt("Gesendet", datum(e.gesendet_am));
  fakt("Fehler", e.fehler);
  if (a && a.maengel && a.maengel.length) {
    const m = $(".maengel", k);
    m.textContent = "Automatische Prüfung: " + a.maengel.join(", ");
    m.classList.remove("versteckt");
  }
  $(".betreff", k).value = a ? a.betreff : `Bewerbung als ${s.titel}`;
  $(".text", k).value = a ? a.absaetze.join("\n\n") : "";
  $(".anzeige", k).href = s.url;
  if (!s.url) $(".anzeige", k).classList.add("versteckt");

  $$(".karten-segment button", k).forEach((b) => b.addEventListener("click", () => kartenVorschau(k, i, b.dataset.art)));
  if (!a) $('.karten-segment button[data-art="anschreiben"]', k).disabled = true;

  // Unterlagen dieser Bewerbung
  const unterlagen = $(".unterlagen-zeile", k);
  const links = [];
  if (e.pdf) links.push(el("a", { class: "knopf klein leise", href: pdfUrl(i), target: "_blank", text: "Anschreiben ↗" }));
  if (zustand.batch.druck) {
    links.push(el("a", { class: "knopf klein leise", target: "_blank",
      href: e.lebenslauf ? mappeUrl(i) : `/unterlagen/${TOKEN}/lebenslauf.pdf`,
      text: e.lebenslauf ? "Lebenslauf für diese Stelle ↗" : "Lebenslauf ↗" }));
  }
  if (e.mappe) links.push(el("a", { class: "knopf klein leise", href: mappeUrl(i), target: "_blank", text: "Ganze Mappe ↗" }));
  if (zustand.batch.anhaenge && zustand.batch.anhaenge.length) {
    links.push(el("span", { class: "gedaempft klein", text: "Im Anhang: " + (e.mappe ? "eine PDF mit allem" : ["Anschreiben", ...zustand.batch.anhaenge].join(", ")) }));
  }
  unterlagen.replaceChildren(...links);

  // ATS-Check
  const atsInhalt = $(".ats-inhalt", k);
  $(".atsPruefen", k).addEventListener("click", async () => {
    try {
      const bericht = await api("/api/ats", { batch: zustand.batchId, i });
      zeigeAts(atsInhalt, bericht, { batch: zustand.batchId, i, gesperrt: e.status === "gesendet" || e.status === "entfernt", kurzprofil: e.kurzprofil });
      $(".ats-punkte", k).textContent = `Trefferquote ${bericht.punkte} % · ${bericht.gefunden.length} von ${bericht.gefunden.length + bericht.fehlend.length} Begriffen`;
    } catch (err) { hinweis(err.message); }
  });

  const gesperrt = e.status === "gesendet" || e.status === "entfernt";
  $$("input, textarea, .speichern, .neu, .entfernen", k).forEach((x) => (x.disabled = gesperrt));

  const einzeln = $(".einzeln", k);
  const kannMail = !gesperrt && perMail(s) && a;
  einzeln.classList.toggle("versteckt", !kannMail);
  einzeln.disabled = !!zustand.batch.einzel_probleme.length;
  einzeln.title = zustand.batch.einzel_probleme.join("\n");
  einzeln.addEventListener("click", () => oeffneFreigabe("einzeln", i));

  const hand = $(".handweg", k);
  if (!gesperrt && !perMail(s)) {
    hand.classList.remove("versteckt");
    $(".handweg-grund", hand).textContent =
      `Nicht automatisch per Mail: ${s.weg_grund || "keine Adresse in der Anzeige"}.`;
    const laden = $(".pdfLaden", hand);
    if (e.pdf) {
      laden.href = pdfUrl(i);
      laden.download = `Anschreiben_${s.firma.replace(/[^\wäöüÄÖÜß-]+/g, "_")}.pdf`;
    } else laden.classList.add("versteckt");
    $(".anlagenLinks", hand).replaceChildren(...(zustand.batch.anlagen || []).map((name, n) =>
      el("a", { class: "knopf klein leise", href: `/api/anlage/${TOKEN}/${n}`, download: name, text: `${name} ↓` })));
    if (e.mappe) $(".anlagenLinks", hand).prepend(el("a", { class: "knopf klein", href: mappeUrl(i), download: `Bewerbung_${s.firma.replace(/[^\wäöüÄÖÜß-]+/g, "_")}.pdf`, text: "Mappe-PDF ↓" }));
    $(".adresseSetzen", hand).addEventListener("click", async () => {
      try {
        await api(`/api/batch/${zustand.batchId}/${i}/adresse`, { email: $(".adresse", hand).value });
        await ladeBatch(zustand.batchId);
      } catch (err) { hinweis(err.message); }
    });
    $(".beworben", hand).addEventListener("click", async () => {
      const weg = $(".wegWahl", hand).value;
      if (!confirm(`„${s.firma}“ als beworben (${$(".wegWahl", hand).selectedOptions[0].text}) eintragen?`)) return;
      try {
        await api(`/api/batch/${zustand.batchId}/${i}/beworben`, { weg });
        await ladeLaeufe(zustand.batchId);
      } catch (err) { hinweis(err.message); }
    });
  }

  $(".speichern", k).addEventListener("click", async () => {
    const absaetze = $(".text", k).value.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
    try {
      await api(`/api/batch/${zustand.batchId}/${i}/text`, { betreff: $(".betreff", k).value, absaetze });
      await ladeBatch(zustand.batchId);
    } catch (err) { hinweis(err.message); }
  });
  $(".neu", k).addEventListener("click", () => starteAuftrag(`/api/batch/${zustand.batchId}/${i}/neu`));
  $(".entfernen", k).addEventListener("click", () => starteAuftrag(`/api/batch/${zustand.batchId}/${i}/entfernen`));

  if (zustand.offen.has(i)) { zustand.offen.delete(i); requestAnimationFrame(auf); }
  return k;
}

// Vorschau in der Karte: dasselbe HTML wie im Druck, laeuft in jedem Browser
async function kartenVorschau(k, i, art) {
  $$(".karten-segment button", k).forEach((b) => b.classList.toggle("aktiv", b.dataset.art === art));
  try {
    const { id } = await api("/api/vorschau", { art, batch: zustand.batchId, i });
    $("iframe", k).src = `/vorschau/${TOKEN}/${id}`;
  } catch (err) {
    $("iframe", k).removeAttribute("src");
    $(".vorschau-fehler", k).textContent = err.message;
  }
}

function pdfUrl(i) {
  return `/api/pdf/${TOKEN}/${zustand.batchId}/${i}?t=${Date.now()}`;
}

function mappeUrl(i) {
  return `/api/mappe/${TOKEN}/${zustand.batchId}/${i}?t=${Date.now()}`;
}

// ---------------------------------------------------------------- ATS-Anzeige (Karten und Lebenslauf)

function chips(liste, klasse) {
  return el("div", { class: "chips" }, ...liste.map((b) => el("span", {
    class: `chip ${klasse} art-${b.art}`, title: b.beleg ? `gefunden: „…${b.beleg}…“` : `Gewicht ${b.gewicht}`, text: b.wort,
  })));
}

function zeigeAts(ziel, b, kontext = {}) {
  const ring = el("div", { class: "ring", style: `--wert:${b.punkte}` }, el("strong", { text: String(b.punkte) }), el("small", { text: "von 100" }));
  const kopf = el("div", { class: "ats-ergebnis-kopf" }, ring, el("div", {},
    el("p", { text: b.titel ? `Anzeige: ${b.titel}` : "" }),
    el("p", { class: "gedaempft", text: b.titel_treffer ? "Der Stellentitel steht im Kopf des Lebenslaufs." : "Der Stellentitel fehlt im Kopf des Lebenslaufs." }),
    b.mit_modell ? el("p", { class: "gedaempft klein", text: "Begriffe zusätzlich vom Modell gezogen." }) : null));
  const teile = [kopf];
  if (b.gefunden.length) teile.push(el("h4", { text: `Gefunden (${b.gefunden.length})` }), chips(b.gefunden, "gut"));
  if (b.fehlend.length) teile.push(el("h4", { text: `Nicht gefunden (${b.fehlend.length})` }), chips(b.fehlend, "fehlt"));
  if (b.hinweise.length) teile.push(el("ul", { class: "hinweise" }, ...b.hinweise.map((h) => el("li", { text: h }))));
  if (kontext.batch !== undefined && !kontext.gesperrt) {
    const feld = el("textarea", { rows: "4", placeholder: "Kurzprofil nur für diese Bewerbung (leer = allgemeines Kurzprofil)" });
    feld.value = kontext.kurzprofil || "";
    const vorschlag = el("button", { class: "knopf klein", text: "Vorschlag vom Modell", onclick: async () => {
      try {
        const v = await auftragErgebnis("/api/ats/kurzprofil", { batch: kontext.batch, i: kontext.i });
        feld.value = v.kurzprofil;
        warn.textContent = v.unbelegt.length ? `Achtung, nicht im Lebenslauf belegt: ${v.unbelegt.join(", ")} – bitte prüfen oder streichen.` : "Nur belegte Begriffe verwendet.";
        warn.className = v.unbelegt.length ? "warnung" : "gedaempft klein";
      } catch (err) { hinweis(err.message); }
    } });
    const warn = el("p", { class: "gedaempft klein" });
    const setzen = el("button", { class: "knopf klein primaer", text: "Für diese Bewerbung übernehmen", onclick: async () => {
      try {
        await api(`/api/batch/${kontext.batch}/${kontext.i}/kurzprofil`, { kurzprofil: feld.value });
        await ladeBatch(zustand.batchId);
      } catch (err) { hinweis(err.message); }
    } });
    teile.push(el("div", { class: "kurzprofil-stelle" }, el("h4", { text: "Kurzprofil für diese Stelle" }), feld, warn,
      el("div", { class: "aktionen" }, vorschlag, setzen)));
  }
  ziel.replaceChildren(...teile);
}

function zeichneVersandleiste() {
  const b = zustand.batch;
  const leiste = $("#versandleiste");
  const perMailOffen = b.eintraege.filter((e) => offen(e) && perMail(e.stelle));
  const mitText = perMailOffen.filter((e) => e.anschreiben);
  const haendisch = b.eintraege.filter((e) => offen(e) && !perMail(e.stelle)).length;
  leiste.classList.toggle("versteckt", !$('section[data-ansicht="lauf"]').offsetParent);
  $("#versandZahl").textContent = (!perMailOffen.length ? "Nichts per Mail offen"
    : mitText.length === perMailOffen.length ? `${perMailOffen.length} bereit zum Senden`
    : `${mitText.length} von ${perMailOffen.length} mit Anschreiben`)
    + (haendisch ? ` · ${haendisch} übers Portal` : "");
  const nachweis = $("#nachweisKnopf");
  nachweis.classList.toggle("versteckt", !b.ungemeldet);
  nachweis.textContent = `Nachweis senden (${b.ungemeldet}) …`;
  nachweis.disabled = !!b.einzel_probleme.length;
  const p = b.versand_probleme;
  $("#versandHinweis").textContent = !p.length ? "Alles geprüft."
    : p.slice(0, 2).join(" · ") + (p.length > 2 ? ` · und ${p.length - 2} weitere` : "");
  $("#versandHinweis").title = p.join("\n");
  $("#freigeben").disabled = !perMailOffen.length || b.versand_probleme.length > 0;
}

const offen = (e) => e.status === "entwurf" || e.status === "fehler";
const perMail = (s) => !!s.email && (!s.weg || s.weg === "email");

async function oeffneFreigabe(modus = "alle", index = null) {
  const b = zustand.batch;
  const status = await api("/api/status");
  const sb = status.pruefungen.find((p) => p.name === "Sachbearbeitung");
  const liste = $("#freigabeListe");
  liste.replaceChildren();
  const auswahl = modus === "einzeln" ? [b.eintraege[index]]
    : modus === "alle" ? b.eintraege.filter((e) => offen(e) && perMail(e.stelle)) : [];
  for (const e of auswahl) {
    liste.append(el("li", {}, el("strong", { text: e.stelle.firma }),
      el("small", { text: `${e.stelle.email} · ${e.anschreiben.betreff}` })));
  }
  liste.classList.toggle("versteckt", !auswahl.length);
  $("#freigabeTitel").textContent = modus === "nachweis" ? "Nachweis an die Sachbearbeitung senden?"
    : modus === "einzeln" ? "Diese Bewerbung senden?" : `${auswahl.length} Bewerbungen senden?`;
  const n = b.ungemeldet + auswahl.length;
  $("#freigabeSb").textContent = !sb.ok
    ? "Keine Sachbearbeitungs-Adresse eingetragen – der Nachweis wird nicht verschickt."
    : modus === "nachweis" ? `Nachweis über ${b.ungemeldet} noch nicht gemeldete Bewerbungen an ${sb.info}.`
    : `Danach: Nachweis über ${n} noch nicht gemeldete Bewerbungen an ${sb.info}.`;
  zustand.freigabe = { modus, index };
  $("#freigabeEingabe").value = "";
  $("#freigabeLos").disabled = true;
  $("#freigabe").showModal();
  $("#freigabeEingabe").focus();
}

$("#freigabeEingabe").addEventListener("input", (ev) => {
  $("#freigabeLos").disabled = ev.target.value !== "SENDEN";
});
function beiAbsenden(dialog, knopfWert, aktion) {
  $("form", dialog).addEventListener("submit", (ev) => {
    if (!ev.submitter || ev.submitter.value !== knopfWert) return;
    aktion();
  });
}

beiAbsenden($("#freigabe"), "senden", () => {
  if ($("#freigabeEingabe").value !== "SENDEN") return;
  const { modus, index } = zustand.freigabe;
  if (modus === "nachweis") starteAuftrag(`/api/batch/${zustand.batchId}/nachweis`, { bestaetigung: "SENDEN" });
  else starteAuftrag(`/api/batch/${zustand.batchId}/senden`,
    { bestaetigung: "SENDEN", nur: modus === "einzeln" ? [index] : null });
});

$("#vonHand").addEventListener("click", () => {
  $("#handDialog form").reset();
  $("#handDialog").showModal();
});
beiAbsenden($("#handDialog"), "anlegen", () => {
  const daten = Object.fromEntries(new FormData($("#handDialog form")));
  daten.batch = zustand.batch && zustand.batch.status === "offen" ? zustand.batchId : "";
  starteAuftrag("/api/hinzufuegen", daten);
});

async function starteAuftrag(pfad, daten = {}) {
  try {
    await api(pfad, daten);
    zustand.auftragLief = true;
    verfolgeAuftrag();
  } catch (err) { hinweis(err.message); }
}

function zeigeAuftrag(a) {
  const feld = $("#auftrag");
  feld.classList.remove("versteckt");
  feld.classList.toggle("fertig", a.fertig && !a.fehler);
  feld.classList.toggle("fehler", !!a.fehler);
  $("#auftragName").textContent = a.fertig ? `${a.name} – ${a.fehler ? "fehlgeschlagen" : "fertig"}` : `${a.name} läuft …`;
  const log = $("#auftragLog");
  log.textContent = a.log.join("\n");
  log.scrollTop = log.scrollHeight;
  $("#auftragZu").classList.toggle("versteckt", !a.fertig);
}

// Startet einen Hintergrundauftrag und liefert sein Ergebnis (fuer Vorschlaege, Tests, Importe)
async function auftragErgebnis(pfad, daten = {}) {
  await api(pfad, daten);
  for (;;) {
    const a = await api("/api/auftrag");
    zeigeAuftrag(a);
    if (a.fertig) {
      if (a.fehler) throw new Error(a.fehler);
      return a.ergebnis;
    }
    await new Promise((r) => setTimeout(r, 900));
  }
}

async function verfolgeAuftrag() {
  const a = await api("/api/auftrag");
  const feld = $("#auftrag");
  if (!a.name) return;
  if (a.fertig && !zustand.auftragLief) return;
  feld.classList.remove("versteckt");
  feld.classList.toggle("fertig", a.fertig && !a.fehler);
  feld.classList.toggle("fehler", !!a.fehler);
  $("#auftragName").textContent = a.fertig ? `${a.name} – ${a.fehler ? "fehlgeschlagen" : "fertig"}` : `${a.name} läuft …`;
  const log = $("#auftragLog");
  log.textContent = a.log.join("\n");
  log.scrollTop = log.scrollHeight;
  $("#auftragZu").classList.toggle("versteckt", !a.fertig);
  $("#neuerLauf").disabled = !a.fertig;
  if (!a.fertig) {
    zustand.auftragLief = true;
    setTimeout(verfolgeAuftrag, 1200);
    return;
  }
  zustand.auftragLief = false;
  await ladeLaeufe(a.ergebnis && a.ergebnis.batch);
}

$("#auftragZu").addEventListener("click", () => $("#auftrag").classList.add("versteckt"));
$("#neuerLauf").addEventListener("click", () => starteAuftrag("/api/lauf"));
$("#freigeben").addEventListener("click", () => oeffneFreigabe("alle"));
$("#nachweisKnopf").addEventListener("click", () => oeffneFreigabe("nachweis"));
$("#verwerfen").addEventListener("click", async () => {
  if (!confirm("Alle offenen Entwürfe dieses Laufs verwerfen? Gesendetes bleibt.")) return;
  try { await api(`/api/batch/${zustand.batchId}/verwerfen`, {}); await ladeLaeufe(zustand.batchId); }
  catch (err) { hinweis(err.message); }
});
$$(".reiter button").forEach((b) => b.addEventListener("click", () => zeige(b.dataset.ansicht)));

function tabelle(ziel, kopf, zeilen, leer) {
  ziel.replaceChildren();
  if (!zeilen.length) {
    ziel.append(el("tr", {}, el("td", { class: "leer", text: leer })));
    return;
  }
  ziel.append(el("tr", {}, ...kopf.map((k) => el("th", { text: k }))));
  zeilen.forEach((z) => ziel.append(el("tr", {}, ...z.map((zelle) => el("td", {}, zelle)))));
}

function link(text, href) {
  return el("a", { href, target: "_blank", rel: "noopener", text });
}

function zeigeHaendisch() {
  const liste = (zustand.batch && zustand.batch.ohne_email) || [];
  const gesperrt = !zustand.batch || zustand.batch.status !== "offen";
  tabelle($("#haendischTabelle"), ["Stelle", "Firma", "Ort", "Beginn", "Warum nicht automatisch", "Passung", ""],
    liste.map((s) => [link(s.titel, s.url), s.firma, s.ort, datum(s.beginn),
      s.weg_grund || "keine Adresse im Anzeigentext", String(s.punkte),
      gesperrt ? "" : el("button", {
        class: "knopf klein", text: "Anschreiben erstellen",
        onclick: async () => {
          await starteAuftrag(`/api/batch/${zustand.batchId}/uebernehmen`, { refnr: s.refnr });
          zeige("lauf");
        },
      })]),
    "Im aktuellen Lauf gibt es keine Stellen zum Selbstbewerben.");
}

async function ladeVerlauf() {
  const zeilen = await api("/api/historie");
  tabelle($("#verlaufTabelle"), ["Gesendet", "Stelle", "Firma", "An", "Rückmeldung"],
    zeilen.map((z) => {
      const wahl = el("select", {
        onchange: async (ev) => {
          try { await api(`/api/batch/${z.batch}/${z.i}/rueckmeldung`, { art: ev.target.value }); }
          catch (err) { hinweis(err.message); }
        },
      }, ...[["", "offen"], ["eingeladen", "eingeladen"], ["absage", "Absage"], ["zusage", "Zusage"]]
        .map(([wert, text]) => el("option", { value: wert, text })));
      wahl.value = z.rueckmeldung || "";
      return [datum(z.datum), link(z.titel, z.url), z.firma, z.email, wahl];
    }),
    "Noch nichts gesendet.");
}

async function ladeStatus() {
  const status = await api("/api/status");
  const ziel = $("#pruefungen");
  ziel.replaceChildren(...status.pruefungen.map((p) =>
    el("li", {}, el("span", { class: p.ok ? "ok" : "nein", text: p.ok ? "✓" : "✕" }), el("strong", { text: p.name }), el("span", { text: p.info }))));
}

$("#linkForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const url = $("#linkEingabe").value.trim();
  if (!url) return;
  const batch = zustand.batch && zustand.batch.status === "offen" ? zustand.batchId : "";
  await starteAuftrag("/api/stelle/link", { url, batch });
  $("#linkEingabe").value = "";
  zeige("lauf");
});

// Lesezeichen "Übernehmen": die Anzeige kommt im Adress-Anker (#import=...) und verlässt nie das Gerät
async function pruefeImport() {
  const treffer = location.hash.match(/^#import=(.+)$/);
  if (!treffer) return;
  history.replaceState(null, "", location.pathname);
  let paket;
  try {
    paket = JSON.parse(decodeURIComponent(escape(atob(treffer[1]))));
  } catch (err) { hinweis("Die übergebene Anzeige ließ sich nicht lesen."); return; }
  const vorschau = await api("/api/stelle/pruefen", paket);
  const fakten = $("#importFakten");
  fakten.replaceChildren();
  const fakt = (dt, dd) => dd && fakten.append(el("dt", { text: dt }), el("dd", { text: dd }));
  fakt("Stelle", vorschau.titel);
  fakt("Firma", vorschau.firma);
  fakt("Ort", [vorschau.plz, vorschau.ort].filter(Boolean).join(" "));
  fakt("Bewerbung", vorschau.email ? `per E-Mail an ${vorschau.email}` : "über das Portal der Anzeige");
  fakt("Quelle", paket.url);
  fakt("Text", `${(vorschau.beschreibung || "").length} Zeichen` + (paket.daten ? " (strukturierte Anzeige)" : " (Seitentext)"));
  zustand.importPaket = paket;
  $("#importDialog").showModal();
}
beiAbsenden($("#importDialog"), "los", () => {
  const batch = zustand.batch && zustand.batch.status === "offen" ? zustand.batchId : "";
  starteAuftrag("/api/stelle/link", { ...zustand.importPaket, batch });
  zeige("lauf");
});

(async function start() {
  try {
    await ladeLaeufe();
    await verfolgeAuftrag();
    let gemerkt = null;
    try { gemerkt = sessionStorage.getItem("ansicht"); } catch (e) { /* egal */ }
    if (gemerkt && gemerkt !== "lauf") zeige(gemerkt);
    else if (!zustand.batch) zeige("einrichtung");
    await pruefeImport();
  } catch (err) { hinweis(err.message); }
})();
