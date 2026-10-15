// JPShot for phones: capture (camera / screenshot / paste / type / share) → OCR → read Japanese.
import { $, $$, toast, openSheet, openViewer, cropper, onLongPress, popOverlay, overlayCount, closeTop } from "./ui.js";
import { JA_RE, hasKanji, kataToHira, loadTokenizer, tokenize, candidates, rubySegments, ankiFurigana,
  display, renderText, romajiMap, romajiSpacing } from "./nlp.js";
import { loadDict, lookup, lookupEnglish, loadAccents } from "./data.js";
import * as G from "./grammar.js";
import * as P from "./pitch.js";
import * as D from "./difficulty.js";
import * as K from "./kanji.js";
import { conjugations, tableHTML } from "./conjugate.js";
import { settings, saveSettings, feat, translate, speak, stopSpeaking, jaVoices, chat, hasWriter, hasNativeVoice } from "./services.js";
import { known, history as hist } from "./store.js";
import * as Anki from "./anki.js";
import * as OCR from "./ocr.js";

const esc = G.esc;
const NATIVE = window.JPShotAndroid || null;   // set when running inside the Android app
const log = (...a) => console.log("[jpshot]", ...a);

// -- features (Settings → Selectable features). Basics are always on. ----------------------------
const FEATURES = [
  ["grammar", "Grammar colors", "Color words by part of speech; grammar notes when you tap a word"],
  ["patterns", "Grammar patterns", "Spot patterns like 〜てしまう or 〜わけじゃない"],
  ["pitch", "Pitch accent", "Pitch-accent colors and high/low marks"],
  ["difficulty", "Word difficulty colors", "Color each word from easy to hard (the sentence level is always shown)"],
  ["known", "Known words", "Mark words you know, sync them from Anki, i+1 badge"],
  ["kanji", "Kanji breakdown", "Parts, meanings, explanations and stroke order"],
  ["forms", "Conjugation tables", "All the forms of a verb or adjective"],
  ["anki", "Anki mining", "Make Anki cards (AnkiConnect, or AnkiMobile on iPhone)"],
  ["ask", "Ask a tutor", "Ask questions about the sentence (needs an API key)"],
  ["shadow", "Shadowing", "Record yourself and compare with the audio"],
];
const BOXES = [
  ["english", "English", "英語"], ["romaji", "Rōmaji", "ローマ字"], ["japanese", "Japanese", "日本語"],
  ["hiragana", "Hiragana", "ひらがな"], ["furigana", "Furigana", "ふりがな"],
];
const MODES = [["grammar", "Grammar", "文法"], ["pitch", "Pitch", "アクセント"], ["difficulty", "Difficulty", "難易度"], ["known", "Known", "既知"]];
const KNOWN_C = "#2fb383", LEARN_C = "#e8556d";

const S = {
  tokenizer: null, lines: [], toks: [], japanese: "", english: "", lang: "ja", image: "", diff: null, matches: [],
  rmap: null, spacing: null, highs: null, sel: null, editing: false, enDirty: false, id: 0, playing: false,
};

// -- theme & settings --------------------------------------------------------------------------
function applySettings() {
  const root = document.documentElement;
  if (settings.theme === "light" || settings.theme === "dark") root.dataset.theme = settings.theme;
  else delete root.dataset.theme;
  root.style.setProperty("--jasize", `${settings.jaSize}px`);
  $("#speed").value = settings.speed;
  $("#speed-label").textContent = `${Number(settings.speed).toFixed(2)}×`;
  if (!MODES.some(([m]) => m === settings.colorMode && feat(m))) settings.colorMode = "none";
}

// -- pages --------------------------------------------------------------------------------------
function showPage(name) {
  for (const p of ["home", "crop", "result"]) $("#" + p).hidden = p !== name;
  $("#dock").hidden = name !== "result";
  $("#btn-new").hidden = name === "home";
  $("#selbar").hidden = true;
  if (name === "home") { stopSpeaking(); renderRecent(); }
  window.scrollTo(0, 0);
}
let page = "home";
function go(name, push = true) {
  if (push && name !== "home" && page === "home") history.pushState({ page: name }, "");
  else if (name !== "home") history.replaceState({ page: name }, "");
  page = name;
  showPage(name);
}
/** Close the top sheet, then run fn once the browser has gone back. */
function afterBack(fn) {
  window.addEventListener("popstate", () => setTimeout(fn, 0), { once: true });
  closeTop();
}
window.addEventListener("popstate", () => {
  if (overlayCount()) { popOverlay(); return; }
  if (page !== "home") { page = "home"; showPage("home"); }
});

// -- startup: tokenizer + data in the background -------------------------------------------------
let tokenizerP = null;
function getTokenizer() {
  if (!tokenizerP) {
    const st = $("#loadstatus");
    st.textContent = "Loading the Japanese dictionary…";
    tokenizerP = (async () => {
      for (let i = 0; i < 50 && !window.kuromoji; i++) await new Promise((r) => setTimeout(r, 100));
      const t = await loadTokenizer();
      st.textContent = "";
      log("tokenizer ready");
      return t;
    })();
    tokenizerP.catch((e) => { st.textContent = "Couldn't load the dictionary: " + e.message; tokenizerP = null; });
  }
  return tokenizerP;
}

// -- capture ---------------------------------------------------------------------------------------
let crop = null, cropImg = null;
async function loadImageFile(blob) {
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.src = url;
  await img.decode();
  // very large camera photos are scaled down to keep OCR quick
  const max = Math.max(img.naturalWidth, img.naturalHeight);
  if (max <= 3000) return img;
  const k = 3000 / max, c = document.createElement("canvas");
  c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  const small = new Image();
  small.src = c.toDataURL("image/jpeg", 0.92);
  await small.decode();
  URL.revokeObjectURL(url);
  return small;
}
async function startCrop(blob) {
  try {
    cropImg = await loadImageFile(blob);
  } catch (e) { toast("Couldn't open that image"); return; }
  const el = $("#crop-img");
  el.src = cropImg.src;
  go("crop");
  if (!crop) crop = cropper($("#crop-stage"), el, $("#crop-box"), (ok) => { $("#crop-use").disabled = !ok; });
  crop.reset();
  OCR.getWorker().catch(() => {});   // warm up the OCR engine while the box is drawn
}
function snapshot(img, r) {
  const { x, y, w, h } = r || { x: 0, y: 0, w: img.naturalWidth, h: img.naturalHeight };
  const k = Math.min(1, 1200 / Math.max(w, h));
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w * k)); c.height = Math.max(1, Math.round(h * k));
  c.getContext("2d").drawImage(img, x, y, w, h, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}
async function runOCR(r) {
  const image = snapshot(cropImg, r);
  go("result");
  resetResult(image);
  setStatus(`<div class="busy"><div class="spin"></div><span id="ocr-msg">Reading text…</span></div><div class="progress"><div id="ocr-bar"></div></div>`);
  try {
    const res = await OCR.recognize(OCR.prepare(cropImg, r), 55, (m) => {
      const msg = $("#ocr-msg"), bar = $("#ocr-bar");
      if (!msg) return;
      msg.textContent = m.status === "recognizing text" ? "Reading text…" : `${m.status[0].toUpperCase()}${m.status.slice(1)} (first time only)…`;
      bar.style.width = `${Math.round((m.progress || 0) * 100)}%`;
    });
    log("ocr:", res);
    if (!res) { toast("No text found"); history.back(); return; }
    await process(res.text, { image, lang: res.language });
  } catch (e) {
    log(e);
    setStatus(`<span class="muted">OCR failed: ${esc(e.message)}</span>`);
  }
}

async function pasteCapture() {
  if (NATIVE) {                       // Android app: read the clipboard natively (WebView can't)
    const img = NATIVE.clipboardImage();
    if (img) return startCrop(await (await fetch(img)).blob());
    const txt = NATIVE.clipboardText();
    if (txt.trim()) return process(txt.trim(), {});
    toast("The clipboard is empty");
    return;
  }
  try {
    if (navigator.clipboard?.read) {
      const items = await navigator.clipboard.read();
      for (const it of items) {
        const t = it.types.find((x) => x.startsWith("image/"));
        if (t) return startCrop(await it.getType(t));
      }
      for (const it of items) {
        if (it.types.includes("text/plain")) {
          const txt = await (await it.getType("text/plain")).text();
          if (txt.trim()) return process(txt.trim(), {});
        }
      }
    } else if (navigator.clipboard?.readText) {
      const txt = await navigator.clipboard.readText();
      if (txt.trim()) return process(txt.trim(), {});
    }
    toast("The clipboard is empty");
  } catch (e) {
    log("clipboard:", e);
    showType();
    toast("Long-press the box and choose Paste");
  }
}
function showType(text = "") {
  $("#typearea").hidden = false;
  const tb = $("#typebox");
  tb.value = text;
  tb.focus();
}

// -- processing --------------------------------------------------------------------------------
function resetResult(image) {
  S.image = image || "";
  $("#boxes").innerHTML = ""; $("#badges").innerHTML = ""; $("#legend").hidden = true; $("#patterns").hidden = true;
  $("#thumb").hidden = !S.image || !settings.showImage;
  if (S.image) $("#thumb-img").src = S.image;
}
function setStatus(html) { $("#status").innerHTML = html; }

async function process(text, { image = "", lang = "", english = "", id = 0 } = {}) {
  text = text.trim();
  if (!text) return;
  if (page !== "result") { go("result"); resetResult(image); }
  else if (image) resetResult(image);
  const ja = [...text].filter((c) => JA_RE.test(c)).length, la = (text.match(/[A-Za-z]/g) || []).length;
  S.lang = lang || (ja >= la * 0.3 && ja > 0 ? "ja" : "en");
  S.id = id || Date.now();
  setStatus(`<div class="busy"><div class="spin"></div>${S.lang === "ja" ? "Reading" : "Translating"}…</div>`);
  try {
    if (S.lang === "ja") {
      S.japanese = text;
      S.english = english;
    } else {
      S.english = text;
      S.japanese = english && JA_RE.test(english) ? english : await translate(text, "en", "ja");
    }
  } catch (e) {
    setStatus(`<span class="muted">${esc(e.message)}</span>`);
    return;
  }
  await analyze();
  if (S.lang === "ja" && !S.english) {
    translate(S.japanese, "ja", "en").then((en) => { S.english = en; renderBoxes(); save(); })
      .catch((e) => { S.english = ""; renderBoxes(); setStatus(`<span class="muted">${esc(e.message)}</span>`); });
  }
  save();
}
function save() {
  hist.add({ id: S.id, time: Date.now(), japanese: S.japanese, english: S.english, lang: S.lang, image: S.image });
}

async function analyze() {
  S.tokenizer = await getTokenizer();
  S.lines = tokenize(S.tokenizer, S.japanese);
  S.toks = S.lines.flat();
  S.rmap = romajiMap(S.lines);
  S.spacing = romajiSpacing(S.lines);
  S.matches = G.detectPatterns(S.lines);
  S.sel = null;
  S.highs = null;
  if (feat("pitch")) { await loadAccents(); S.highs = P.sentenceHighs(S.lines); }
  setStatus("");
  renderAll();
  D.estimate(S.lines).then((d) => { S.diff = d; renderBadges(); if (settings.colorMode === "difficulty") renderBoxes(); });
}

// -- rendering --------------------------------------------------------------------------------
function renderAll() { renderChips(); renderBadges(); renderPatterns(); renderBoxes(); }

function sections() {
  const s = BOXES.map(([b]) => b).filter((b) => settings.sections.includes(b));
  return s.length ? s : ["japanese"];
}
function renderChips() {
  const shown = new Set(sections());
  const bc = $("#box-chips");
  bc.innerHTML = BOXES.map(([k, en, ja]) => `<button class="chip${shown.has(k) ? " on" : ""}" data-box="${k}">${en}<small>${ja}</small></button>`).join("");
  for (const b of $$(".chip", bc)) {
    const wasLong = onLongPress(b, () => toggleBox(b.dataset.box, true));
    b.addEventListener("click", () => { if (!wasLong()) toggleBox(b.dataset.box, false); });
  }
  const modes = MODES.filter(([k]) => feat(k));
  const mc = $("#mode-chips");
  mc.hidden = !modes.length;
  mc.innerHTML = modes.map(([k, en, ja]) => `<button class="chip${settings.colorMode === k ? " on" : ""}" data-mode="${k}">${en}<small>${ja}</small></button>`).join("");
  for (const b of $$(".chip", mc)) b.addEventListener("click", () => setMode(b.dataset.mode));
}
async function toggleBox(k, multi) {
  if (S.enDirty) await applyEnglishEdit();
  let s = sections();
  if (multi) {
    s = s.includes(k) ? s.filter((x) => x !== k) : [...s, k];
    if (!s.length) s = [k];
    if (navigator.vibrate) navigator.vibrate(15);
  } else s = s.length === 1 && s[0] === k ? s : [k];
  settings.sections = BOXES.map(([b]) => b).filter((b) => s.includes(b));
  saveSettings();
  renderChips(); renderBoxes();
}
async function setMode(m) {
  settings.colorMode = settings.colorMode === m ? "none" : m;
  saveSettings();
  if (settings.colorMode === "pitch" && !S.highs) { await loadAccents(); S.highs = P.sentenceHighs(S.lines); }
  renderChips(); renderBoxes();
}

function renderBadges() {
  let h = "";
  const d = S.diff;
  if (d) h += `<a id="diff-badge" style="color:${d.color}">${d.stars}</a> <a id="diff-badge2" class="small">${d.jlpt} · ${esc(d.label)}</a>`;
  if (feat("known") && S.toks.length) {
    const unknown = known.unknownWords(S.lines).length;
    h += unknown === 1 ? ` <span class="small" style="color:${KNOWN_C}">i+1 ✓ one new word</span>`
      : ` <span class="small muted">${unknown ? `${unknown} new words` : "all words known"}</span>`;
  }
  $("#badges").innerHTML = h;
  for (const id of ["#diff-badge", "#diff-badge2"]) {
    const el = $(id);
    if (el) el.onclick = () => openSheet(`Difficulty: ${d.jlpt} · ${d.label}`,
      `<div style="font-size:24px;color:${d.color}">${d.stars}</div><ul>${d.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` +
      `<div class="muted small">An estimate from kanji grades, word frequency and grammar.</div>`);
  }
}
function renderPatterns() {
  const el = $("#patterns");
  el.hidden = !feat("patterns") || !S.matches.length;
  if (el.hidden) return;
  el.innerHTML = S.matches.map((m, i) => `<a data-p="${i}">${esc(m.pattern.form)} <span class="muted">${m.pattern.jlpt}</span></a>`).join("");
  for (const a of $$("a", el)) {
    a.onclick = () => {
      const m = S.matches[a.dataset.p];
      const on = !a.classList.contains("on");
      $$("a", el).forEach((x) => x.classList.remove("on"));
      $$(".tok.mark").forEach((x) => x.classList.remove("mark"));
      if (on) {
        a.classList.add("on");
        const line = S.lines[m.line];
        for (let i = m.first; i <= m.last; i++) $$(`[data-i="${S.toks.indexOf(line[i])}"]`).forEach((x) => x.classList.add("mark"));
        toast(`${m.pattern.form} — ${m.pattern.meaning}`, 4000);
      }
    };
  }
}

function tokColor(t) {
  switch (settings.colorMode) {
    case "grammar": return t.lookupable || t.pos === "助詞" ? G.colorFor(t) : null;
    case "pitch": return P.wordColor(t);
    case "difficulty": return D.wordColor(S.diff, t);
    case "known":
      if (!known.counts(t)) return null;
      if (known.isKnown(t)) return KNOWN_C;
      return known.sets().unknown.has(t.base) || known.sets().unknown.has(t.surface) ? LEARN_C : null;
    default: return null;
  }
}
const tokSpan = (t, inner, color) =>
  `<span class="tok${S.sel === t ? " sel" : ""}" data-i="${S.toks.indexOf(t)}"${color ? ` style="color:${color}"` : ""}>${inner}</span>`;

/** kana with each sound colored high (orange) or low (blue) */
function pitchKana(text, highs) {
  const ms = P.morae(text);
  if (!highs || ms.length !== highs.length) return esc(text);
  return ms.map((m, i) => `<span style="color:${highs[i] ? P.HIGH : P.LOW}">${esc(m)}</span>`).join("");
}
function furiganaHTML(t, pitchOn) {
  const hideRuby = settings.furiganaUnknownOnly && feat("known") && known.isKnown(t);
  const segs = hideRuby ? [[t.surface, ""]] : rubySegments(t);
  const highs = pitchOn ? S.highs.get(t) : null;
  if (!highs) return segs.map(([s, r]) => (r ? `<ruby>${esc(s)}<rt>${esc(r)}</rt></ruby>` : esc(s))).join("");
  // walk the sounds of the reading across the segments
  const ms = P.morae(t.reading || kataToHira(t.surface));
  if (ms.length !== highs.length) return segs.map(([s, r]) => (r ? `<ruby>${esc(s)}<rt>${esc(r)}</rt></ruby>` : esc(s))).join("");
  let mi = 0;
  const take = (kana) => {
    let len = 0, out = "";
    while (mi < ms.length && len < kana.length) {
      out += `<span style="color:${highs[mi] ? P.HIGH : P.LOW}">${esc(ms[mi])}</span>`;
      len += ms[mi].length; mi++;
    }
    return out;
  };
  return segs.map(([s, r]) => {
    if (r) return `<ruby>${esc(s)}<rt>${take(r)}</rt></ruby>`;
    if (hasKanji(s)) return esc(s);
    return take(kataToHira(s));
  }).join("");
}
function boxBody(key) {
  if (key === "english") {
    if (S.editing) return `<textarea id="en-edit">${esc(S.english)}</textarea>`;
    if (!S.english) return `<span class="muted">${S.lang === "ja" ? "translating…" : ""}</span>`;
    return esc(S.english).split(/(\s+)/).map((w) => (/\w/.test(w) ? `<span class="en">${w}</span>` : w)).join("");
  }
  const pitchOn = settings.colorMode === "pitch" && S.highs;
  return S.lines.map((line) => line.map((t) => {
    if (t.space) return key === "romaji" ? " " : esc(t.surface);
    const c = tokColor(t);
    if (key === "romaji") return (S.spacing.has(t) ? " " : "") + tokSpan(t, esc(display(t, "romaji", S.rmap)), c);
    if (key === "japanese") return tokSpan(t, esc(t.surface), c);
    if (key === "hiragana") {
      const txt = display(t, "hiragana");
      if (pitchOn && S.highs.get(t)) return tokSpan(t, pitchKana(kataToHira(txt), S.highs.get(t)), null);
      return tokSpan(t, esc(txt), pitchOn ? null : c);
    }
    return tokSpan(t, furiganaHTML(t, pitchOn), pitchOn ? null : c);   // furigana
  }).join("")).join("<br>");
}
function plainText(key) {
  if (key === "english") return S.english;
  if (key === "furigana") return ankiFurigana(S.lines);
  return renderText(S.lines, key);
}
function renderBoxes() {
  const shown = sections();
  const boxes = $("#boxes");
  boxes.innerHTML = shown.map((k) => {
    const [, en, ja] = BOXES.find(([b]) => b === k);
    const edit = k === "english" ? (S.editing ? `<button data-act="en-apply">Update Japanese</button><button data-act="en-cancel">Cancel</button>`
      : `<button data-act="en-edit">✎ Edit</button>`) : k === "japanese" ? `<button data-act="ja-edit">✎ Edit</button>` : "";
    const say = k === "english" ? "" : `<button data-act="say">🔊</button>`;
    return `<div class="box" data-key="${k}"><div class="bh"><b>${en}</b><span class="muted">${ja}</span><span class="sp"></span>${say}${edit}` +
      `<button data-act="copy">Copy</button></div><div class="bb">${boxBody(k)}</div></div>`;
  }).join("");
  // legend
  const lg = $("#legend");
  const set = new Set(shown);
  let legend = "";
  if (settings.colorMode === "grammar") legend = G.legendHTML();
  else if (settings.colorMode === "pitch") legend = P.legendHTML(set);
  else if (settings.colorMode === "difficulty") legend = D.legendHTML();
  else if (settings.colorMode === "known") legend = `<span style="color:${KNOWN_C}">■</span> known · <span style="color:${LEARN_C}">■</span> learning · plain = not rated <span class="muted">(tap a word to rate it)</span>`;
  lg.innerHTML = legend; lg.hidden = !legend;
  const ta = $("#en-edit");
  if (ta) { ta.addEventListener("input", () => { S.enDirty = true; }); ta.focus(); }
}

// -- box actions -------------------------------------------------------------------------------
$("#boxes").addEventListener("click", async (e) => {
  const act = e.target.closest("[data-act]");
  if (act) {
    const key = act.closest(".box").dataset.key;
    switch (act.dataset.act) {
      case "copy": await copyText(plainText(key)); break;
      case "say": speak(S.japanese, settings.speed, settings.voice); break;
      case "en-edit": S.editing = true; S.enDirty = false; renderBoxes(); break;
      case "en-cancel": S.editing = false; S.enDirty = false; renderBoxes(); break;
      case "en-apply": await applyEnglishEdit(); break;
      case "ja-edit": editJapanese(); break;
    }
    return;
  }
  const tok = e.target.closest(".tok");
  if (tok) { openWord(S.toks[Number(tok.dataset.i)]); return; }
  const en = e.target.closest(".en");
  if (en && !window.getSelection().toString()) openEnglish(en.textContent);
});
async function applyEnglishEdit() {
  const ta = $("#en-edit");
  const val = (ta ? ta.value : S.english).trim();
  S.editing = false; S.enDirty = false;
  if (!val || val === S.english) { renderBoxes(); return; }
  S.english = val;
  setStatus(`<div class="busy"><div class="spin"></div>Updating the Japanese…</div>`);
  try {
    S.japanese = await translate(val, "en", "ja");
    await analyze();
    save();
  } catch (e) { setStatus(`<span class="muted">${esc(e.message)}</span>`); renderBoxes(); }
}
function editJapanese() {
  const s = openSheet("Edit the Japanese", `<textarea class="typebox" id="ja-edit">${esc(S.japanese)}</textarea>` +
    `<div class="row" style="margin-top:8px"><button class="btn primary" id="ja-apply">Update</button></div>` +
    `<div class="hint">Fix OCR mistakes here; the English is translated again.</div>`);
  $("#ja-apply", s.body).onclick = async () => {
    const v = $("#ja-edit", s.body).value.trim();
    afterBack(() => { if (v && v !== S.japanese) { S.english = ""; process(v, { image: S.image, lang: "ja", id: S.id }); } });
  };
}
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); toast("Copied"); }
  catch (_) {
    const ta = document.createElement("textarea");
    ta.value = t; document.body.append(ta); ta.select();
    document.execCommand("copy"); ta.remove(); toast("Copied");
  }
}
function selectTok(t) {
  S.sel = t;
  $$(".tok.sel").forEach((x) => x.classList.remove("sel"));
  if (t) $$(`[data-i="${S.toks.indexOf(t)}"]`).forEach((x) => x.classList.add("sel"));
}

// -- word sheet -----------------------------------------------------------------------------------
async function openWord(t) {
  if (!t || !t.lookupable) return;
  selectTok(t);
  const s = openSheet(t.base || t.surface, `<div class="busy"><div class="spin"></div>Looking up…</div>`, { onClose: () => selectTok(null) });
  if (feat("pitch")) await loadAccents();
  const res = await lookup(candidates(t));
  const e0 = res.entries[0];
  const word = res.query || t.base || t.surface;
  const reading = (e0 && e0.reading) || (word === t.surface ? t.reading : "");
  const desc = G.describe(S.lines, t);
  let h = `<div class="whead"><span class="w">${esc(word)}</span>${reading && reading !== word ? `<span class="r">${esc(reading)}</span>` : ""}` +
    `<button class="say" data-say="${esc(word)}" title="Say the word">🔊</button>` +
    (desc.phrase && desc.phrase !== word ? `<button class="say" data-say="${esc(desc.phrase)}" title="Say the phrase">🗣</button>` : "") + `</div>`;
  if (t.surface !== word) h += `<div class="muted small">as written: ${esc(t.surface)}${desc.summary ? ` — ${esc(desc.summary)}` : ""}</div>`;
  if (feat("known") && known.counts(t)) {
    const k = known.isKnown(t);
    h += `<div style="margin:6px 0"><button class="btn" data-known style="color:${k ? KNOWN_C : ""}">${k ? "✓ Known — tap to unmark" : "Mark as known"}</button></div>`;
  }
  if (feat("pitch")) { const ph = P.patternHTML(t); if (ph) h += ph; }
  if (feat("grammar")) h += G.describeHTML(desc);
  if (feat("patterns")) {
    for (const m of G.patternsFor(S.matches, S.lines, t)) {
      h += `<div><span class="tag" style="background:#50a0ff">${esc(m.pattern.form)}</span> ${esc(m.pattern.meaning)} <span class="muted small">${m.pattern.jlpt}</span></div>`;
    }
  }
  if (res.entries.length) {
    h += res.entries.map((e) => `<div class="entry"><b style="font-family:var(--ja)">${esc(e.word)}</b>` +
      (e.reading && e.reading !== e.word ? ` 【${esc(e.reading)}】` : "") +
      (e.common ? ` <span class="tag" style="background:${KNOWN_C}">common</span>` : "") +
      `<ol>${e.senses.map((x) => `<li>${esc(x.glosses.join("; "))} <span class="pos">${esc((x.pos || []).join(", "))}</span></li>`).join("")}</ol></div>`).join("");
  } else h += `<div class="muted">No dictionary entry.</div>`;
  if (feat("forms")) { const rows = conjugations(t); if (rows.length) h += `<details><summary>Forms</summary>${tableHTML(rows)}</details>`; }
  const meaning = e0 ? e0.senses[0].glosses.slice(0, 3).join(", ") : "";
  if (feat("anki")) h += `<div style="margin:10px 0"><button class="btn" data-mine>＋ Make a card with this word</button></div>`;
  const kanjiChars = feat("kanji") ? K.kanjiOf(word) : [];
  if (kanjiChars.length) {
    h += (hasWriter() && kanjiChars.length > 1 ? `<div id="word-why"><b>Why:</b> <i class="story">✍ writing…</i></div>` : "") +
      kanjiChars.map((c) => `<div data-kanji="${esc(c)}"><div class="busy"><div class="spin"></div>${esc(c)}…</div></div>`).join("");
  }
  s.body.innerHTML = h;
  s.body.addEventListener("click", (ev) => {
    const say = ev.target.closest("[data-say]");
    if (say) speak(say.dataset.say, settings.speed, settings.voice);
    const st = ev.target.closest("[data-strokes]");
    if (st) openStrokes(st.dataset.strokes);
    if (ev.target.closest("[data-known]")) {
      const now = known.toggle(t);
      const b = ev.target.closest("[data-known]");
      b.textContent = now ? "✓ Known — tap to unmark" : "Mark as known"; b.style.color = now ? KNOWN_C : "";
      renderBadges(); renderBoxes(); selectTok(t);
    }
    if (ev.target.closest("[data-mine]")) openMine({ word, reading, meaning });
  });
  if (kanjiChars.length) fillKanji(s.body, kanjiChars, word, reading, meaning);
}
const kanjiCache = new Map();
async function fillKanji(body, chars, word, reading, meaning) {
  const infos = [];
  for (const c of chars) {
    if (!kanjiCache.has(c)) kanjiCache.set(c, K.info(c, word).catch(() => null));
    const k = await kanjiCache.get(c);
    const el = body.querySelector(`[data-kanji="${CSS.escape(c)}"]`);
    if (!k || !el) continue;
    infos.push(k);
    const writer = hasWriter() && !k.storyAI;
    el.innerHTML = K.kanjiHTML(k, { pending: writer });
    if (writer) {
      K.writeKanji(k).then((txt) => { if (txt) { k.story = txt; k.storyAI = true; } })
        .catch((e) => log("explain:", e.message))
        .finally(() => { el.innerHTML = K.kanjiHTML(k); });
    }
  }
  const why = body.querySelector("#word-why");
  if (why) {
    try {
      const txt = await K.writeWord(word, reading, meaning, infos);
      why.innerHTML = `<b>Why:</b> <span class="story">${esc(txt)}</span>`;
    } catch (e) { why.innerHTML = `<span class="muted small">Couldn't write an explanation: ${esc(e.message)}</span>`; }
  }
}
async function openStrokes(c) {
  const k = await kanjiCache.get(c);
  if (!k || !k.svg) return;
  const s = openSheet(`Stroke order: ${c}`, `<div class="strokes">${K.strokeOrderHTML(k)}</div>` +
    `<div class="row" style="justify-content:center;margin-top:10px"><button class="btn" id="replay">↻ Replay</button></div>` +
    `<div class="hint" style="text-align:center">${k.strokes ? k.strokes + " strokes · " : ""}stroke colors match the parts</div>`);
  $("#replay", s.body).onclick = () => { const b = $(".strokes", s.body); b.innerHTML = K.strokeOrderHTML(k); };
}
async function openEnglish(raw) {
  const w = raw.replace(/[^A-Za-z'-]/g, "");
  if (!w) return;
  const s = openSheet(w, `<div class="busy"><div class="spin"></div>Looking up…</div>`);
  const entries = await lookupEnglish(w);
  let h = entries.length ? entries.map((e) => `<div class="entry"><div class="whead"><span class="w" style="font-size:24px">${esc(e.word)}</span>` +
    (e.reading && e.reading !== e.word ? `<span class="r">${esc(e.reading)}</span>` : "") +
    `<button class="say" data-say="${esc(e.word)}">🔊</button></div><div>${esc(e.senses[0].glosses.join("; "))}</div></div>`).join("")
    : `<div class="muted">No dictionary match.</div>`;
  h += `<div id="en-tr" class="muted small"></div>`;
  s.body.innerHTML = h;
  s.body.addEventListener("click", (ev) => { const b = ev.target.closest("[data-say]"); if (b) speak(b.dataset.say, settings.speed, settings.voice); });
  translate(w, "en", "ja").then((j) => { const el = $("#en-tr", s.body); if (el) el.textContent = `Translator: ${j}`; }).catch(() => {});
}

// -- selection translate -----------------------------------------------------------------------
let selTimer = 0, selText = "";
document.addEventListener("selectionchange", () => {
  clearTimeout(selTimer);
  selTimer = setTimeout(async () => {
    const sel = window.getSelection();
    const text = sel.toString().trim();
    const bar = $("#selbar");
    if (!text || page !== "result" || !sel.anchorNode || !$("#boxes").contains(sel.anchorNode) || overlayCount()) {
      if (!text) bar.hidden = true;
      return;
    }
    if (text === selText && !bar.hidden) return;
    selText = text;
    const isJa = JA_RE.test(text);
    bar.hidden = false;
    bar.innerHTML = `<div style="font-family:var(--ja)">${esc(text)}</div><div class="story" id="sel-tr">…</div>` +
      `<div class="act"><a id="sel-say">🔊 Listen</a><a id="sel-copy">Copy</a><span class="sp" style="flex:1"></span><a id="sel-x">✕</a></div>`;
    let tr = "";
    $("#sel-x").onclick = () => { bar.hidden = true; sel.removeAllRanges(); };
    $("#sel-copy").onclick = () => copyText(tr ? `${text}\n${tr}` : text);
    $("#sel-say").onclick = () => speak(isJa ? text : tr || text, settings.speed, settings.voice);
    try { tr = await translate(text, isJa ? "ja" : "en", isJa ? "en" : "ja"); } catch (e) { tr = ""; }
    const el = $("#sel-tr");
    if (el && selText === text) el.textContent = tr || "(translation unavailable)";
  }, 450);
});

// -- playback -------------------------------------------------------------------------------------
$("#btn-play").onclick = () => {
  if (S.playing) { stopSpeaking(); setPlaying(false); return; }
  setPlaying(true);
  speak(S.japanese, settings.speed, settings.voice, () => setPlaying(false));
};
function setPlaying(on) { S.playing = on; $("#btn-play").textContent = on ? "■ Stop" : "▶ Read"; }
$("#speed").addEventListener("input", (e) => {
  settings.speed = Number(e.target.value);
  $("#speed-label").textContent = `${settings.speed.toFixed(2)}×`;
  saveSettings();
});

function renderActions() {
  const a = [["share", "Share"]];
  if (feat("anki")) a.push(["mine", "＋ Anki"]);
  if (feat("ask")) a.push(["ask", "Ask"]);
  if (feat("shadow")) a.push(["shadow", "Shadow"]);
  $("#actions").innerHTML = a.map(([k, l]) => `<button class="btn" data-a="${k}">${l}</button>`).join("");
}
$("#actions").addEventListener("click", (e) => {
  const b = e.target.closest("[data-a]");
  if (!b) return;
  ({ share: shareResult, mine: () => openMine({}), ask: openAsk, shadow: openShadow })[b.dataset.a]();
});
$("#thumb").addEventListener("click", () => S.image && openViewer(S.image));

async function shareResult() {
  const text = `${S.japanese}\n${renderText(S.lines, "hiragana")}\n${S.english}`;
  try {
    const files = [];
    if (S.image) {
      const blob = await (await fetch(S.image)).blob();
      const f = new File([blob], "jpshot.jpg", { type: blob.type });
      if (navigator.canShare && navigator.canShare({ files: [f] })) files.push(f);
    }
    if (navigator.share) { await navigator.share(files.length ? { text, files } : { text }); return; }
  } catch (e) { if (e.name === "AbortError") return; }
  copyText(text);
}

// -- Anki --------------------------------------------------------------------------------------
async function openMine({ word = "", reading = "", meaning = "" }) {
  if (!word && S.sel) { word = S.sel.base; reading = S.sel.reading; }
  const d = S.diff;
  const s = openSheet("Make an Anki card", `<div class="set">
    <div class="field"><span class="muted small">Sentence</span><textarea id="m-sentence" rows="2">${esc(S.japanese)}</textarea></div>
    <div class="field"><span class="muted small">English</span><textarea id="m-english" rows="2">${esc(S.english)}</textarea></div>
    <div class="field"><span class="muted small">Target word (optional)</span><input type="text" id="m-word" value="${esc(word)}"></div>
    <div class="field"><span class="muted small">Word reading</span><input type="text" id="m-reading" value="${esc(reading)}"></div>
    <div class="field"><span class="muted small">Word meaning</span><input type="text" id="m-meaning" value="${esc(meaning)}"></div>
    <div class="field"><span class="muted small">Notes</span><input type="text" id="m-notes" value=""></div>
    <label class="opt"><input type="checkbox" id="m-reading-card" ${settings.ankiReading ? "checked" : ""}><span>Reading card<small>image + Japanese on the front</small></span></label>
    <label class="opt"><input type="checkbox" id="m-hearing-card" ${settings.ankiHearing ? "checked" : ""}><span>Hearing card<small>audio on the front</small></span></label>
    <label class="opt"><input type="checkbox" id="m-font" ${settings.ankiRandomFont ? "checked" : ""}><span>Random font &amp; size<small>so you learn the characters, not one font</small></span></label>
    ${S.image ? `<label class="opt"><input type="checkbox" id="m-image" checked><span>Include the screenshot</span></label>` : ""}
    <h4>AnkiConnect (Android app or desktop Anki)</h4>
    <div class="field"><span class="muted small">Deck</span><select id="m-deck"><option>${esc(settings.ankiDeck || "Default")}</option></select></div>
    <div class="row"><button class="btn primary" id="m-add">Add card</button><span id="m-msg" class="small muted"></span></div>
    <h4>iPhone (AnkiMobile)</h4>
    <div class="row"><a class="btn" id="m-mobile">Send to AnkiMobile</a><button class="btn" id="m-copy">Copy fields</button></div>
    <div class="hint">AnkiMobile can't receive images or audio this way. It needs a note type named “${esc(settings.ankiMobileType)}” (see the guide).</div>
  </div>`);
  const B = s.body;
  const card = () => ({
    sentence: $("#m-sentence", B).value.trim(), english: $("#m-english", B).value.trim(),
    furigana: ankiFurigana(S.lines), word: $("#m-word", B).value.trim(), wordReading: $("#m-reading", B).value.trim(),
    wordMeaning: $("#m-meaning", B).value.trim(), notes: $("#m-notes", B).value.trim(),
    reading: $("#m-reading-card", B).checked, hearing: $("#m-hearing-card", B).checked, randomFont: $("#m-font", B).checked,
    difficulty: d ? `${d.stars} ${d.jlpt} · ${d.label}` : "", audioText: S.japanese,
    image: $("#m-image", B)?.checked ? S.image : "",
  });
  const sel = $("#m-deck", B);
  Anki.invoke("deckNames").then((decks) => {
    const cur = settings.ankiDeck || "Default";
    sel.innerHTML = [...new Set([cur, ...decks])].map((x) => `<option${x === cur ? " selected" : ""}>${esc(x)}</option>`).join("") +
      `<option value="__new">＋ New deck…</option>`;
  }).catch(() => { $("#m-msg", B).textContent = "AnkiConnect not reachable"; });
  sel.onchange = async () => {
    if (sel.value !== "__new") { settings.ankiDeck = sel.value; saveSettings(); return; }
    const name = (prompt("New deck name") || "").trim();
    if (!name) { sel.selectedIndex = 0; return; }
    try { await Anki.invoke("createDeck", { deck: name }); } catch (e) { toast(e.message); }
    sel.insertAdjacentHTML("afterbegin", `<option selected>${esc(name)}</option>`);
    sel.value = name; settings.ankiDeck = name; saveSettings();
  };
  $("#m-add", B).onclick = async () => {
    const c = card();
    if (!c.sentence) { toast("The sentence is empty"); return; }
    if (!c.reading && !c.hearing) { toast("Pick Reading and/or Hearing"); return; }
    $("#m-msg", B).textContent = "Adding…";
    try {
      settings.ankiReading = c.reading; settings.ankiHearing = c.hearing; settings.ankiRandomFont = c.randomFont; saveSettings();
      await Anki.addCard(c);
      toast("Card added ✓"); closeTop();
    } catch (e) { $("#m-msg", B).textContent = e.message; }
  };
  $("#m-mobile", B).onclick = () => { location.href = Anki.ankiMobileURL(card()); };
  $("#m-copy", B).onclick = () => { const c = card(); copyText([c.sentence, c.furigana, c.english, c.word, c.wordReading, c.wordMeaning].filter(Boolean).join("\n")); };
}

// -- Ask a tutor ---------------------------------------------------------------------------------
function openAsk() {
  const s = openSheet("Ask a tutor", hasWriter() ? `<div class="chat" id="chat"><div class="muted small">Ask anything about:<br><span style="font-family:var(--ja)">${esc(S.japanese)}</span></div></div>`
    : `<div>Add an Anthropic API key in Settings → Explanations to ask questions.</div>`, { full: true });
  if (!hasWriter()) return;
  s.foot.innerHTML = `<div class="chatin"><input id="ask-in" placeholder="Why is は used here?" enterkeyhint="send"><button class="btn primary" id="ask-go">Ask</button></div>`;
  const msgs = [];
  const system = `You are a friendly, concise Japanese tutor. The learner is reading this Japanese: ${S.japanese}\n` +
    `Translation: ${S.english}\nAnswer in English, briefly and clearly. When you write Japanese, add the reading in parentheses. Plain text only, no markdown.`;
  const send = async () => {
    const inp = $("#ask-in", s.foot), q = inp.value.trim();
    if (!q) return;
    inp.value = "";
    const box = $("#chat", s.body);
    box.insertAdjacentHTML("beforeend", `<div class="msg"><div class="you">You: ${esc(q)}</div><div class="ans"><i class="story">✍ writing…</i></div></div>`);
    const ans = box.lastElementChild.querySelector(".ans");
    msgs.push({ role: "user", content: q });
    try {
      const a = await chat(msgs, system, 700);
      msgs.push({ role: "assistant", content: a });
      ans.textContent = a;
    } catch (e) { msgs.pop(); ans.innerHTML = `<span class="muted">${esc(e.message)}</span>`; }
    s.body.scrollTop = s.body.scrollHeight;
  };
  $("#ask-go", s.foot).onclick = send;
  $("#ask-in", s.foot).addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
}

// -- Shadowing ---------------------------------------------------------------------------------
function openShadow() {
  let rec = null, chunks = [], url = "", stream = null;
  const s = openSheet("Shadowing", `<div style="font:20px/1.8 var(--ja);margin-bottom:10px">${esc(S.japanese)}</div>
    <div class="row"><button class="btn" id="sh-orig">▶ Original</button><button class="btn primary" id="sh-rec">● Record</button>
    <button class="btn" id="sh-mine" disabled>▶ Mine</button><button class="btn" id="sh-both" disabled>▶ Both</button></div>
    <div class="hint">Listen, then record yourself saying it at the same speed. Compare the rhythm and pitch.</div>`,
  { onClose: () => { if (rec && rec.state === "recording") rec.stop(); stream?.getTracks().forEach((t) => t.stop()); } });
  const B = s.body;
  const playMine = (then) => { if (!url) return; const a = new Audio(url); a.onended = then || null; a.play(); };
  $("#sh-orig", B).onclick = () => speak(S.japanese, settings.speed, settings.voice);
  $("#sh-mine", B).onclick = () => playMine();
  $("#sh-both", B).onclick = () => speak(S.japanese, settings.speed, settings.voice, () => playMine());
  $("#sh-rec", B).onclick = async () => {
    const btn = $("#sh-rec", B);
    if (rec && rec.state === "recording") { rec.stop(); return; }
    try {
      stream = stream || await navigator.mediaDevices.getUserMedia({ audio: true });
      rec = new MediaRecorder(stream); chunks = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        if (url) URL.revokeObjectURL(url);
        url = URL.createObjectURL(new Blob(chunks, { type: rec.mimeType }));
        btn.textContent = "● Record again";
        $("#sh-mine", B).disabled = $("#sh-both", B).disabled = false;
      };
      rec.start();
      btn.textContent = "■ Stop";
    } catch (e) { toast("Microphone not available: " + e.message); }
  };
}

// -- history -----------------------------------------------------------------------------------
const histRow = (c) => `<div class="recent" data-id="${c.id}">${c.image ? `<img src="${c.image}" alt="">` : ""}` +
  `<div class="t">${esc(c.japanese.replace(/\n/g, " "))}<div class="muted small" style="font-family:system-ui">${esc((c.english || "").slice(0, 80))}</div></div>` +
  `<button class="icon-btn" data-del="${c.id}" title="Delete">🗑</button></div>`;
async function renderRecent() {
  const all = await hist.all();
  $("#btn-history").hidden = !all.length;
  $("#recent").innerHTML = all.length ? `<h4 class="muted small" style="margin:18px 2px 4px">RECENT</h4>` + all.slice(0, 5).map(histRow).join("") : "";
}
async function openHistory() {
  const all = await hist.all();
  const s = openSheet("History", all.length ? `<input type="text" id="h-q" placeholder="Search…" style="width:100%;padding:10px;border-radius:10px;border:1px solid var(--line);background:var(--panel2);color:var(--text)"><div id="h-list">${all.map(histRow).join("")}</div>` : `<div class="muted">Nothing yet.</div>`, { full: true });
  const q = $("#h-q", s.body);
  if (q) q.oninput = () => { const v = q.value.trim(); $("#h-list", s.body).innerHTML = all.filter((c) => !v || c.japanese.includes(v) || (c.english || "").toLowerCase().includes(v.toLowerCase())).map(histRow).join(""); };
  s.body.addEventListener("click", (e) => histClick(e, true));
}
async function histClick(e, inSheet) {
  const del = e.target.closest("[data-del]");
  if (del) {
    await hist.remove(Number(del.dataset.del));
    del.closest(".recent").remove();
    if (!inSheet) renderRecent();
    return;
  }
  const row = e.target.closest(".recent");
  if (!row) return;
  const c = (await hist.all()).find((x) => x.id === Number(row.dataset.id));
  if (!c) return;
  const open = () => {
    go("result"); resetResult(c.image);
    process(c.lang === "en" ? c.english : c.japanese, { image: c.image, lang: c.lang, english: c.lang === "en" ? c.japanese : c.english, id: c.id });
  };
  if (inSheet) afterBack(open); else open();
}
$("#recent").addEventListener("click", (e) => histClick(e, false));

// -- settings -----------------------------------------------------------------------------------
function openSettings() {
  const opt = (k, label, sub = "") => `<label class="opt"><input type="checkbox" data-k="${k}" ${settings[k] ? "checked" : ""}><span>${label}${sub ? `<small>${sub}</small>` : ""}</span></label>`;
  const text = (k, label, type = "text", ph = "") => `<div class="field"><span class="muted small">${label}</span><input type="${type}" data-k="${k}" value="${esc(settings[k] ?? "")}" placeholder="${esc(ph)}" autocomplete="off" autocapitalize="off" spellcheck="false"></div>`;
  const voices = jaVoices();
  const s = openSheet("Settings", `<div class="set">
    <h4>Look</h4>
    <div class="field"><span class="muted small">Theme</span><select data-k="theme">${["system", "light", "dark"].map((t) => `<option ${settings.theme === t ? "selected" : ""}>${t}</option>`).join("")}</select></div>
    <div class="field"><span class="muted small">Japanese text size: <b id="sz">${settings.jaSize}px</b></span><input type="range" min="16" max="44" data-k="jaSize" value="${settings.jaSize}"></div>
    ${opt("showImage", "Show the screenshot above the text")}
    <h4>Voice</h4>
    <div class="field"><select data-k="voice"><option value="">${hasNativeVoice() ? "Phone's Japanese voice (Android settings → Text-to-speech)" : voices.length ? "Default Japanese voice" : "Google voice (no Japanese voice on this phone)"}</option>${voices.map((v) => `<option ${settings.voice === v.name ? "selected" : ""} value="${esc(v.name)}">${esc(v.name)}</option>`).join("")}</select></div>
    <div class="row"><button class="btn" id="v-test">🔊 Test voice</button></div>
    ${feat("kanji") || feat("ask") ? `<h4>Explanations</h4>
      ${text("apiKey", "Anthropic API key (stays on this phone)", "password", "sk-ant-…")}
      ${text("model", "Model")}
      <div class="row"><button class="btn" id="k-test">Test</button><span id="k-msg" class="small muted"></span></div>
      <div class="hint">Get a key at console.anthropic.com → API Keys. Explanations are cached, so each kanji costs a fraction of a cent once.</div>` : ""}
    ${feat("anki") ? `<h4>Anki</h4>
      ${text("ankiUrl", "AnkiConnect address", "url")}
      ${text("ankiTags", "Tags")}
      <div class="row"><button class="btn" id="a-test">Test connection</button><span id="a-msg" class="small muted"></span></div>
      ${text("ankiMobileProfile", "AnkiMobile profile (iPhone, optional)")}
      ${text("ankiMobileDeck", "AnkiMobile deck")}
      ${text("ankiMobileType", "AnkiMobile note type")}` : ""}
    ${feat("known") ? `<h4>Known words</h4>
      <div class="hint" id="kn-count">${known.total().toLocaleString()} known words${known.data.lastSync ? ` · last Anki sync ${esc(known.data.lastSync)}` : ""}</div>
      ${opt("furiganaUnknownOnly", "Furigana only over words I don't know")}
      ${text("knownQuery", "Anki search for known words", "text", "deck:Kaishi*")}
      ${text("knownFields", "Word fields")}
      <div class="row"><button class="btn" id="kn-sync">Sync from Anki</button></div>
      <div class="field"><span class="muted small">…or paste a word list</span><textarea id="kn-list" rows="3" placeholder="食べる, 学校, …"></textarea></div>
      <div class="row"><button class="btn" id="kn-import">Import list</button></div>` : ""}
    <h4>Selectable features</h4>
    <div class="hint">The basics are always on: capture, translation, furigana, rōmaji, audio, dictionary and difficulty. Turn on extras here.</div>
    ${FEATURES.map(([k, l, sub]) => `<label class="opt"><input type="checkbox" data-feat="${k}" ${feat(k) ? "checked" : ""}><span>${l}<small>${sub}</small></span></label>`).join("")}
    <h4>About</h4><div class="hint">JPShot web · dictionary: JMdict (EDRDG) · kanji: KANJIDIC2, KanjiVG · pitch: Kanjium · OCR: Tesseract</div>
  </div>`, { full: true, onClose: () => { renderActions(); if (page === "result" && S.toks.length) { analyze(); } } });
  const B = s.body;
  B.addEventListener("input", (e) => {
    const k = e.target.dataset.k;
    if (k) {
      settings[k] = e.target.type === "checkbox" ? e.target.checked : e.target.type === "range" ? Number(e.target.value) : e.target.value.trim();
      if (k === "jaSize") $("#sz", B).textContent = `${settings.jaSize}px`;
      saveSettings(); applySettings();
    }
  });
  B.addEventListener("change", (e) => {
    const f = e.target.dataset.feat;
    if (!f) return;
    settings.features = settings.features.filter((x) => x !== f).concat(e.target.checked ? [f] : []);
    saveSettings(); applySettings();
    const scroll = B.scrollTop;
    afterBack(() => { openSettings(); const nb = $$(".sheet .sb").pop(); if (nb) nb.scrollTop = scroll; });
  });
  $("#v-test", B).onclick = () => speak("こんにちは。日本語を勉強しましょう。", settings.speed, settings.voice);
  const kt = $("#k-test", B);
  if (kt) kt.onclick = async () => {
    const m = $("#k-msg", B); m.textContent = "Testing…";
    try { const r = await chat([{ role: "user", content: "Reply with just: OK" }], "", 10); m.textContent = `✓ Works (${r.trim()})`; }
    catch (e) { m.textContent = "✗ " + e.message; }
  };
  const at = $("#a-test", B);
  if (at) at.onclick = async () => {
    const m = $("#a-msg", B); m.textContent = "Testing…";
    try { const v = await Anki.invoke("version"); m.textContent = `✓ Connected (AnkiConnect v${v})`; } catch (e) { m.textContent = "✗ " + e.message; }
  };
  const ks = $("#kn-sync", B);
  if (ks) ks.onclick = async () => {
    ks.disabled = true; ks.textContent = "Syncing…";
    try { toast(await Anki.syncKnown(), 5000); } catch (e) { toast(e.message, 5000); }
    ks.disabled = false; ks.textContent = "Sync from Anki";
    $("#kn-count", B).textContent = `${known.total().toLocaleString()} known words · last Anki sync ${known.data.lastSync}`;
  };
  const ki = $("#kn-import", B);
  if (ki) ki.onclick = () => {
    const n = known.importList($("#kn-list", B).value);
    toast(`Imported ${n} words`);
    $("#kn-count", B).textContent = `${known.total().toLocaleString()} known words`;
  };
}

// -- share target (Android: Share → JPShot) ----------------------------------------------------
async function handleShare() {
  const params = new URLSearchParams(location.search);
  history.replaceState(null, "", location.pathname);
  const shared = params.get("text") || params.get("title") || "";
  if (params.has("share") && "caches" in window) {
    const cache = await caches.open("jpshot-share");
    const img = await cache.match("shared-image");
    const txt = await cache.match("shared-text");
    await cache.delete("shared-image"); await cache.delete("shared-text");
    if (img) return startCrop(await img.blob());
    if (txt) { const t = (await txt.text()).trim(); if (t) return process(t, {}); }
  }
  if (shared.trim()) process(shared.trim(), {});
}

// -- wiring --------------------------------------------------------------------------------------
$("#cap-camera").onclick = () => $("#file-camera").click();
$("#cap-photo").onclick = () => $("#file-photo").click();
$("#cap-paste").onclick = pasteCapture;
$("#cap-type").onclick = () => showType();
for (const id of ["#file-camera", "#file-photo"]) {
  $(id).addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) startCrop(f); });
}
$("#type-go").onclick = () => { const v = $("#typebox").value.trim(); if (v) { $("#typearea").hidden = true; process(v, {}); } };
$("#type-cancel").onclick = () => { $("#typearea").hidden = true; };
$("#crop-cancel").onclick = () => history.back();
$("#crop-all").onclick = () => runOCR(null);
$("#crop-use").onclick = () => runOCR(crop.get());
$("#btn-new").onclick = () => { if (page !== "home") history.back(); };
$("#btn-history").onclick = openHistory;
$("#btn-settings").onclick = openSettings;
document.addEventListener("paste", (e) => {
  if (page !== "home" || e.target.closest?.("textarea,input")) return;
  const file = [...(e.clipboardData?.files || [])][0];
  const t = e.clipboardData?.getData("text/plain");
  if (file && file.type.startsWith("image/")) { e.preventDefault(); startCrop(file); }
  else if (t && t.trim()) { e.preventDefault(); process(t.trim(), {}); }
});

// -- Android app (native wrapper): bubble, screenshots and shares arrive here -----------------------
function setupNative() {
  if (!NATIVE) return;
  const grid = $(".capture-grid");
  const b = document.createElement("button");
  b.className = "capture"; b.id = "cap-bubble"; b.style.gridColumn = "span 2"; b.style.minHeight = "72px";
  grid.prepend(b);
  const label = () => {
    const on = NATIVE.bubbleRunning();
    b.innerHTML = on ? `<span class="ico">🫧</span>Bubble is on<span class="sub">tap to turn it off</span>`
      : `<span class="ico">🫧</span>Start the bubble<span class="sub">a floating capture button over your other apps</span>`;
  };
  label();
  b.onclick = () => { if (NATIVE.bubbleRunning()) NATIVE.stopBubble(); else NATIVE.startBubble(); setTimeout(label, 600); };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { label(); window.jpshotNativeInbox(); } });
}
window.jpshotNativeInbox = async () => {
  if (!NATIVE) return;
  const shot = NATIVE.takeShot();
  if (shot) {
    try { await startCrop(await (await fetch(shot)).blob()); } catch (e) { toast("Couldn't open the screenshot"); }
    return;
  }
  const text = NATIVE.takeText();
  if (text && text.trim()) process(text.trim(), {});
};

const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
$("#share-hint").innerHTML = NATIVE
  ? "Tip: start the <b>bubble</b>, then go back to what you're reading. Tap the bubble whenever you get stuck. JPShot opens with your screenshot (split screen works too). Long-press the bubble to close it."
  : isIOS
  ? "Tip: take a screenshot, then tap <b>Screenshot</b> — your newest screenshot is first in the picker. Add JPShot to your Home Screen (Share → Add to Home Screen) for one-tap access."
  : "Tip: install JPShot (browser menu → Install app / Add to Home screen). Then you can screenshot anything and use <b>Share → JPShot</b>.";

applySettings();
renderActions();
renderRecent();
getTokenizer();
setTimeout(() => { loadDict(); if (feat("pitch")) loadAccents(); }, 1500);
setupNative();
if (NATIVE) window.jpshotNativeInbox(); else handleShare();
if (!NATIVE && "serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch((e) => log("sw:", e));
if (feat("known") && known.data.lastSync && Date.now() - Date.parse(known.data.lastSync) > 30 * 60e3) {
  Anki.syncKnown().then((r) => log("known sync:", r)).catch(() => {});
}
window.jpshot = { S, process, settings };   // for debugging from the browser console
