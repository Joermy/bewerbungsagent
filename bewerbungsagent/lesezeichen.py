"""Zwei Lesezeichen (Bookmarklets) fuer den eigenen Browser.

"Übernehmen": auf einer Stellenanzeige anklicken - die Anzeige (schema.org/JobPosting,
sonst markierter oder sichtbarer Text) geht an die lokale App und wird nach einer
Bestaetigung dort ein Entwurf. Das funktioniert auch auf Seiten mit Captcha oder
Anmeldung, weil man selbst im Browser ist und die Seite normal geladen hat.

"Ausfüllen": fuellt Bewerbungsformulare mit den eigenen Kontaktdaten vor (Name, E-Mail,
Telefon, Adresse, Links). Es schickt nichts ab und laesst Passwort- und Dateifelder aus.
Die Daten stehen im Lesezeichen selbst - es verlaesst nichts den Rechner.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

UEBERNEHMEN_JS = r"""
(()=>{
  const finde=(o)=>{
    if(!o)return null;
    if(Array.isArray(o)){for(const x of o){const r=finde(x);if(r)return r}return null}
    if(typeof o!=="object")return null;
    const t=o["@type"];
    if(t==="JobPosting"||(Array.isArray(t)&&t.includes("JobPosting")))return o;
    for(const k of ["@graph","mainEntity","itemListElement","item"]){if(o[k]){const r=finde(o[k]);if(r)return r}}
    return null};
  let jp=null;
  for(const s of document.querySelectorAll('script[type="application/ld+json"]')){
    try{jp=finde(JSON.parse(s.textContent))}catch(e){}
    if(jp)break}
  const auswahl=String(getSelection()).trim();
  const d={url:location.href,titel:(document.querySelector("h1")||{}).innerText||document.title};
  if(jp&&!auswahl){d.daten=jp}else{d.text=(auswahl||document.body.innerText).slice(0,16000)}
  const roh=JSON.stringify(d);
  const b64=btoa(unescape(encodeURIComponent(roh)));
  window.open("__APP__/#import="+b64,"_blank","noopener")
})();
"""

AUSFUELLEN_JS = r"""
(()=>{
  const P=__DATEN__;
  const regeln=[
    ["vorname",/(first.?name|vorname|given.?name|fname)/i,["given-name"]],
    ["nachname",/(last.?name|nachname|surname|family.?name|lname|zuname)/i,["family-name"]],
    ["name",/(^|[^a-z])(full.?name|ihr name|vollst.ndiger name|name)$/i,["name"]],
    ["email",/(e-?mail)/i,["email"]],
    ["telefon",/(phone|telefon|mobil|handy|tel$|tel[^a-z])/i,["tel","tel-national"]],
    ["strasse",/(street|stra(ss|ß)e|address.?line.?1|anschrift|adresse$)/i,["street-address","address-line1"]],
    ["plz",/(zip|postal|plz|postleitzahl)/i,["postal-code"]],
    ["ort",/(city|^ort|wohnort|stadt|town|locality)/i,["address-level2"]],
    ["land",/(country|^land$)/i,["country-name","country"]],
    ["linkedin",/linkedin/i,[]],
    ["github",/github/i,[]],
    ["web",/(website|homepage|portfolio|webseite|^url$|personal.?site)/i,["url"]],
    ["geburtsdatum",/(birth|geburt)/i,["bday"]]
  ];
  const text=(el)=>{
    const teile=[el.name,el.id,el.placeholder,el.getAttribute("aria-label"),el.getAttribute("data-automation-id")];
    if(el.id){const l=el.ownerDocument.querySelector('label[for="'+CSS.escape(el.id)+'"]');if(l)teile.push(l.innerText)}
    const umschliessend=el.closest("label");if(umschliessend)teile.push(umschliessend.innerText);
    return teile.filter(Boolean).join(" ").trim()};
  const setze=(el,wert)=>{
    const proto=el.tagName==="TEXTAREA"?HTMLTextAreaElement.prototype:el.tagName==="SELECT"?HTMLSelectElement.prototype:HTMLInputElement.prototype;
    const setter=Object.getOwnPropertyDescriptor(proto,"value").set;
    if(el.tagName==="SELECT"){
      const opt=[...el.options].find(o=>o.text.trim().toLowerCase()===String(wert).toLowerCase());
      if(!opt)return false;wert=opt.value}
    setter.call(el,wert);
    el.dispatchEvent(new Event("input",{bubbles:true}));
    el.dispatchEvent(new Event("change",{bubbles:true}));
    el.style.outline="2px solid #9b5cff";el.style.outlineOffset="1px";
    return true};
  const doks=[document];
  for(const f of document.querySelectorAll("iframe")){try{if(f.contentDocument)doks.push(f.contentDocument)}catch(e){}}
  let n=0;
  for(const dok of doks){
    for(const el of dok.querySelectorAll("input,textarea,select")){
      const typ=(el.type||"").toLowerCase();
      if(["hidden","password","file","checkbox","radio","submit","button","search"].includes(typ))continue;
      if(el.disabled||el.readOnly||(el.value&&el.tagName!=="SELECT")||el.offsetParent===null)continue;
      const auto=(el.getAttribute("autocomplete")||"").toLowerCase().split(" ").pop();
      const t=text(el);
      let feld=null;
      for(const [name,muster,autos] of regeln){if(autos.includes(auto)){feld=name;break}}
      if(!feld&&typ==="email")feld="email";
      if(!feld&&typ==="tel")feld="telefon";
      if(!feld){for(const [name,muster] of regeln){if(muster.test(t)){feld=name;break}}}
      if(!feld||!P[feld])continue;
      if(setze(el,P[feld]))n++}}
  const hinweis=document.createElement("div");
  hinweis.textContent=n?n+" Felder ausgefüllt – bitte prüfen, nichts wurde abgeschickt.":"Keine passenden leeren Felder gefunden.";
  hinweis.style.cssText="position:fixed;z-index:2147483647;right:16px;bottom:16px;padding:12px 16px;border-radius:10px;background:#1d2029;color:#fff;font:14px/1.4 system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.35)";
  document.body.appendChild(hinweis);setTimeout(()=>hinweis.remove(),4500)
})();
"""


def _klein(js: str) -> str:
    zeilen = [z.strip() for z in js.strip().splitlines()]
    return "".join(z for z in zeilen if z and not z.startswith("//"))


def _als_link(js: str) -> str:
    return "javascript:" + quote(_klein(js), safe="()=>{}[];,.!?:*+-/_~|$@")


def uebernehmen(port: int = 8765) -> str:
    return _als_link(UEBERNEHMEN_JS.replace("__APP__", f"http://127.0.0.1:{int(port)}"))


def formulardaten(profil, lebenslauf: dict | None = None) -> dict:
    """Die Werte fuer das Ausfuellen - aus Profil und Lebenslauf."""
    person = (lebenslauf or {}).get("person") or {}
    name = person.get("name") or profil.name
    teile = name.split()
    plz_ort = person.get("plz_ort") or profil.plz_ort
    plz, _, ort = plz_ort.partition(" ")
    if not re.fullmatch(r"\d{4,5}", plz):
        plz, ort = "", plz_ort
    return {
        "name": name,
        "vorname": " ".join(teile[:-1]) if len(teile) > 1 else name,
        "nachname": teile[-1] if teile else "",
        "email": person.get("email") or profil.email,
        "telefon": person.get("telefon") or profil.telefon,
        "strasse": person.get("strasse") or profil.strasse,
        "plz": plz,
        "ort": ort,
        "land": "Deutschland",
        "web": person.get("web") or profil.portfolio,
        "github": person.get("github", ""),
        "linkedin": person.get("linkedin", ""),
        "geburtsdatum": person.get("geburtsdatum", ""),
    }


def ausfuellen(daten: dict) -> str:
    sauber = {k: str(v) for k, v in daten.items() if v}
    roh = json.dumps(sauber, ensure_ascii=False).replace("</", "<\\/")
    return _als_link(AUSFUELLEN_JS.replace("__DATEN__", roh))
