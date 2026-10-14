// Offline data built by tools/build_web_data.py: dictionary, kanji info, pitch accents.
import { kataToHira } from "./nlp.js";

const cache = {};
async function loadJSON(name) {
  if (!(name in cache)) {
    cache[name] = fetch(`data/${name}.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  }
  return cache[name];
}

// -- dictionary ------------------------------------------------------------------------
let dictIndex = null, dictData = null;
export async function loadDict() {
  if (dictIndex) return true;
  const d = await loadJSON("dict");
  if (!d) return false;
  dictData = d;
  dictIndex = new Map();
  d.e.forEach((e, i) => {
    for (const f of [...e[0], ...e[1]]) {
      if (!dictIndex.has(f)) dictIndex.set(f, []);
      dictIndex.get(f).push(i);
    }
  });
  return true;
}

function toEntry(i) {
  const [kanji, kana, senses, common] = dictData.e[i];
  return {
    word: kanji[0] || kana[0], reading: kana[0] || "", common: !!common,
    senses: senses.map(([pos, glosses]) => ({ glosses, pos: pos.map((p) => posLabel(p)) })),
    forms: kanji, kana,
  };
}

const POS_SHORT = { n: "noun", v1: "ichidan verb", vt: "transitive", vi: "intransitive", "adj-i": "い-adjective",
  "adj-na": "な-adjective", "adj-no": "takes の", adv: "adverb", prt: "particle", exp: "expression",
  "vs": "する verb", "vs-i": "する verb", conj: "conjunction", int: "interjection", pn: "pronoun",
  suf: "suffix", pref: "prefix", ctr: "counter", "adv-to": "adverb (と)", "aux-v": "auxiliary verb" };
function posLabel(p) {
  if (POS_SHORT[p]) return POS_SHORT[p];
  if (/^v5/.test(p)) return "godan verb";
  return (dictData.t[p] || p).replace(/\s*\(.*?\)/g, "");
}

/** Look up the first candidate that has entries. Returns {query, entries} */
export async function lookup(cands) {
  const ok = await loadDict();
  for (const q of cands) {
    if (ok && dictIndex.has(q)) {
      const ids = dictIndex.get(q);
      const entries = ids.map(toEntry).sort((a, b) =>
        (b.forms.includes(q) - a.forms.includes(q)) || (b.common - a.common));
      return { query: q, entries: entries.slice(0, 3) };
    }
  }
  // not in the offline dictionary: try jisho.org (works when the browser allows it)
  for (const q of cands.slice(0, 1)) {
    try {
      const r = await fetch(`https://jisho.org/api/v1/search/words?keyword=${encodeURIComponent(q)}`);
      const data = (await r.json()).data || [];
      const hits = data.filter((d) => (d.japanese || []).some((j) => j.word === q || j.reading === q)).slice(0, 3);
      if (hits.length) {
        return { query: q, entries: hits.map((d) => ({
          word: d.japanese[0].word || d.japanese[0].reading, reading: d.japanese[0].reading || "",
          common: !!d.is_common,
          senses: (d.senses || []).slice(0, 5).map((s) => ({ glosses: s.english_definitions, pos: s.parts_of_speech })),
          forms: [], kana: [] })) };
      }
    } catch (_) { /* offline or blocked */ }
  }
  return { query: "", entries: [] };
}

/** Japanese words for an English word (offline: gloss match in the common dictionary). */
export async function lookupEnglish(word) {
  if (!(await loadDict())) return [];
  const w = word.toLowerCase();
  const scored = [];
  dictData.e.forEach((e, i) => {
    let best = 0;
    e[2].forEach(([, glosses], si) => {
      for (let g of glosses) {
        g = g.toLowerCase().replace(/^to /, "");
        if (g === w) best = Math.max(best, 10 - si);
        else if (g.split(/[;,] ?/).includes(w)) best = Math.max(best, 6 - si);
      }
    });
    if (best) scored.push([best + (e[3] ? 3 : 0), i]);
  });
  scored.sort((a, b) => b[0] - a[0]);
  return scored.slice(0, 4).map(([, i]) => toEntry(i));
}

/** Common words containing a kanji (for "words with 変"). */
export async function wordsWith(ch, exclude = "") {
  if (!(await loadDict())) return [];
  const out = [];
  for (const e of dictData.e) {
    if (!e[3]) continue;
    const f = e[0].find((x) => x.includes(ch) && x.length <= 4);
    if (f && f !== exclude) {
      out.push({ word: f, reading: e[1][0] || "", gloss: e[2][0][1].slice(0, 2).join(", ") });
      if (out.length >= 4) break;
    }
  }
  return out;
}

export async function isCommon(word) {
  if (!(await loadDict())) return null;
  const ids = dictIndex.get(word);
  if (!ids) return null;
  return ids.some((i) => dictData.e[i][3]);
}

// -- kanji ---------------------------------------------------------------------------
let kanjiData = null;
export async function kanjiInfo(ch) {
  if (!kanjiData) kanjiData = (await loadJSON("kanji")) || {};
  const k = kanjiData[ch];
  if (!k) return null;
  const [meanings, on, kun, strokes, grade, jlpt, freq] = k;
  return { char: ch, meanings, on, kun, strokes, grade, jlpt, freq };
}

// -- pitch accents -----------------------------------------------------------------------
let accents = null;
export async function loadAccents() {
  if (!accents) accents = (await loadJSON("accents")) || {};
  return accents;
}
export function accentEntries(word) {
  return (accents && accents[word]) || [];
}
export { kataToHira };
