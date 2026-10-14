// Anki: AnkiConnect (desktop Anki, or the "AnkiConnect Android" app on Android) and AnkiMobile on iPhone.
import { esc } from "./grammar.js";
import { cleanField, known, readingFromFurigana } from "./store.js";
import { googleTTS, settings } from "./services.js";

export async function invoke(action, params = {}) {
  let r;
  try {
    r = await fetch(settings.ankiUrl, { method: "POST", body: JSON.stringify({ action, version: 6, params }) });
  } catch (e) {
    throw new Error("Can't reach Anki. Desktop: open Anki with the AnkiConnect add-on. Android: install and open " +
      "“AnkiConnect Android”. Then allow this site in AnkiConnect's CORS list (see the guide).");
  }
  const d = await r.json();
  if (d.error) throw new Error(d.error);
  return d.result;
}

export const MODEL = "JPShot Sentence";
const FIELDS = ["Sentence", "Furigana", "English", "Image", "Audio", "HearingAudio", "Word", "WordReading",
  "WordMeaning", "Notes", "Reading", "Hearing", "RandomFont", "Voice", "Difficulty"];
const FONTS = ["Noto Sans CJK JP", "Noto Serif CJK JP", "Noto Sans JP", "Noto Serif JP", "IPAexGothic", "IPAexMincho",
  "M PLUS 1p", "M PLUS Rounded 1c", "Kosugi Maru", "Sawarabi Mincho", "Zen Maru Gothic", "Klee One", "Kiwi Maru",
  "Shippori Mincho", "Yomogi", "Hachi Maru Pop", "Yusei Magic", "Yu Gothic", "Yu Mincho", "Meiryo", "MS Mincho",
  "BIZ UDGothic", "BIZ UDMincho", "Hiragino Sans", "Hiragino Mincho ProN", "Hiragino Maru Gothic ProN", "Klee",
  "Tsukushi A Round Gothic", "YuKyokasho", "Toppan Bunkyu Mincho"];
const SHUFFLE = `<button class="jps-shuffle" onclick="jpshotShuffle()">🔀</button><script>(function(){var f=[${FONTS.map((x) => JSON.stringify(x)).join(",")}];
function ok(n){var c=document.createElement("canvas").getContext("2d"),t="日本語の文字";return["monospace","serif"].some(function(b){c.font="40px "+b;var w=c.measureText(t).width;c.font="40px '"+n+"', "+b;return c.measureText(t).width!==w;});}
var a=window.__jpsFonts||(window.__jpsFonts=f.filter(ok));if(!a.length)a=["serif","sans-serif"];
window.jpshotShuffle=function(){var e=document.getElementById("jps-sentence");if(!e)return;var n=a[Math.floor(Math.random()*a.length)];
e.style.fontFamily=(n==="serif"||n==="sans-serif")?n:"'"+n+"', sans-serif";e.style.fontSize=(1.3+Math.random()*1.2).toFixed(2)+"em";};jpshotShuffle();})();</script>`;
const ANSWER = `<div class="jps-img">{{Image}}</div><div class="jps-furigana">{{furigana:Furigana}}</div>
<div class="jps-english">{{English}}</div>{{#Word}}<div class="jps-word">{{furigana:Word}}{{#WordMeaning}}<div class="jps-wm">{{WordMeaning}}</div>{{/WordMeaning}}</div>{{/Word}}
{{#Notes}}<div class="jps-notes">{{Notes}}</div>{{/Notes}}{{#Difficulty}}<div class="jps-diff">{{Difficulty}}</div>{{/Difficulty}}`;
const TEMPLATES = {
  Reading: { Front: `{{#Reading}}<div class="jps-img">{{Image}}</div><div id="jps-sentence" class="jps-sentence">{{Sentence}}</div>{{#RandomFont}}${SHUFFLE}{{/RandomFont}}{{/Reading}}`,
    Back: `{{#Reading}}${ANSWER}<div>{{Audio}}</div>{{/Reading}}` },
  Hearing: { Front: `{{#Hearing}}<div class="jps-img">{{Image}}</div><div class="jps-listen">🎧 Listen</div>{{HearingAudio}}{{/Hearing}}`,
    Back: `{{#Hearing}}${ANSWER}{{/Hearing}}` },
};
const CSS = `.card{font-family:"Noto Sans CJK JP","Hiragino Sans","Yu Gothic",sans-serif;font-size:20px;text-align:center;line-height:1.6;color:#1d1d1f;background:#fafafa}
.nightMode .card,.card.nightMode{color:#e7e7ea;background:#1f2023}.jps-img img{max-width:100%;max-height:42vh;border-radius:8px}
.jps-sentence{font-size:1.8em;margin:.6em .4em}.jps-furigana{font-size:1.6em;line-height:2.1}.jps-furigana rt{font-size:.5em;color:#e8556d}
.jps-english{color:#888;margin:.3em .6em .8em}.jps-word{display:inline-block;padding:.4em .8em;border-radius:8px;background:rgba(232,85,109,.08)}
.jps-wm{font-size:.85em;color:#888;white-space:pre-line;text-align:left}.jps-notes,.jps-diff{font-size:.8em;color:#999;margin-top:.6em}
.jps-listen{font-size:1.6em;margin:.8em}.jps-shuffle{border:none;background:transparent;font-size:1.1em;opacity:.6}`;

export async function ensureModel() {
  const models = await invoke("modelNames");
  if (!models.includes(MODEL)) {
    await invoke("createModel", { modelName: MODEL, inOrderFields: FIELDS, css: CSS, isCloze: false,
      cardTemplates: Object.entries(TEMPLATES).map(([Name, t]) => ({ Name, ...t })) });
  } else {
    try {
      await invoke("updateModelTemplates", { model: { name: MODEL, templates: TEMPLATES } });
      await invoke("updateModelStyling", { model: { name: MODEL, css: CSS } });
    } catch (_) { /* older AnkiConnect */ }
  }
}

const field = (s) => esc(s || "").replace(/\n/g, "<br>");

/** Add a JPShot card through AnkiConnect. imageDataUrl: "data:image/png;base64,…" or "". */
export async function addCard(c) {
  await ensureModel();
  const stamp = Date.now();
  const note = {
    deckName: settings.ankiDeck || "Default", modelName: MODEL,
    fields: { Sentence: field(c.sentence), Furigana: field(c.furigana || c.sentence), English: field(c.english),
      Word: field(c.word), WordReading: field(c.wordReading), WordMeaning: field(c.wordMeaning), Notes: field(c.notes),
      Reading: c.reading ? "1" : "", Hearing: c.hearing ? "1" : "", RandomFont: c.randomFont ? "1" : "",
      Voice: c.hearing ? "Google" : "", Difficulty: field(c.difficulty) },
    tags: (settings.ankiTags || "").split(/\s+/).filter(Boolean).concat(c.extraTags || []),
    options: { allowDuplicate: !!c.allowDuplicate, duplicateScope: "deck" },
    audio: [],
  };
  const audioUrl = googleTTS(c.audioText || c.sentence);   // Anki downloads it itself
  if (c.reading) note.audio.push({ url: audioUrl, filename: `jpshot-${stamp}.mp3`, fields: ["Audio"] });
  if (c.hearing) note.audio.push({ url: audioUrl, filename: `jpshot-${stamp}-h.mp3`, fields: ["HearingAudio"] });
  if (c.image) {
    const ext = /^data:image\/jpe?g/.test(c.image) ? "jpg" : "png";
    note.picture = [{ data: c.image.split(",")[1], filename: `jpshot-${stamp}.${ext}`, fields: ["Image"] }];
  }
  return invoke("addNote", { note });
}

/** iPhone: AnkiMobile's add-note link (text fields only; the note type must exist in AnkiMobile). */
export function ankiMobileURL(c) {
  const p = new URLSearchParams();
  if (settings.ankiMobileProfile) p.set("profile", settings.ankiMobileProfile);
  p.set("type", settings.ankiMobileType || MODEL);
  p.set("deck", settings.ankiMobileDeck || "Default");
  const f = { Sentence: c.sentence, Furigana: c.furigana, English: c.english, Word: c.word, WordReading: c.wordReading,
    WordMeaning: c.wordMeaning, Notes: c.notes, Reading: c.reading ? "1" : "", Hearing: "", RandomFont: c.randomFont ? "1" : "",
    Difficulty: c.difficulty };
  for (const [k, v] of Object.entries(f)) if (v) p.set("fld" + k, v);
  if (settings.ankiTags) p.set("tags", settings.ankiTags);
  return "anki://x-callback-url/addnote?" + p.toString().replace(/\+/g, "%20");
}

/** Sync known words from reviewed Anki notes (AnkiConnect). Returns a report string. */
export async function syncKnown() {
  const q = settings.knownQuery.trim() ? `(${settings.knownQuery}) -is:new` : "-is:new";
  const ids = await invoke("findNotes", { query: q });
  const wanted = settings.knownFields.split(",").map((f) => f.trim().toLowerCase()).filter(Boolean);
  const words = new Set(), kana = new Set(), used = {};
  for (let i = 0; i < ids.length; i += 500) {
    for (const note of await invoke("notesInfo", { notes: ids.slice(i, i + 500) })) {
      const nf = note.fields || {};
      const byLower = Object.fromEntries(Object.keys(nf).map((n) => [n.toLowerCase(), n]));
      let found = wanted.filter((w) => byLower[w]).map((w) => byLower[w]);
      if (!found.length) {
        const first = Object.keys(nf).sort((a, b) => nf[a].order - nf[b].order)[0];
        const w = first && cleanField(nf[first].value);
        if (w && w.length <= 12 && /[぀-ヿ㐀-鿿]/.test(w)) found = [first];
      }
      for (const name of found) {
        const w = cleanField(nf[name].value);
        if (w && w.length <= 20 && /[぀-ヿ㐀-鿿]/.test(w)) { words.add(w); used[name] = (used[name] || 0) + 1; }
      }
      const rf = READ(byLower);
      if (rf) { const r = readingFromFurigana(nf[rf].value); if (r) kana.add(r); }
    }
  }
  for (const w of words) if (/^[぀-ヿー]+$/.test(w)) kana.add(w);
  known.setAnki(words, kana);
  if (!ids.length) return `No reviewed notes found for “${q}”.`;
  return `Synced ${words.size.toLocaleString()} words from ${ids.length.toLocaleString()} reviewed notes` +
    (Object.keys(used).length ? ` (field ${Object.keys(used).join(", ")})` : "");
}
const READ = (byLower) => { const k = ["word furigana", "word reading", "vocabulary-furigana", "vocabulary-kana", "furigana", "reading", "kana"].find((x) => byLower[x]); return k && byLower[k]; };
