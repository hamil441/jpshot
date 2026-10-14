// Pitch accent (Tokyo standard) from the Kanjium list: patterns, colors, per-sound high/low.
import { accentEntries } from "./data.js";
import { display, hasKanji } from "./nlp.js";

const SMALL = new Set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ");
export const COLORS = { heiban: "#3b8fe8", atamadaka: "#e8556d", nakadaka: "#f0a030", odaka: "#2fb383" };
export const HIGH = "#ff8a3d", LOW = "#5aa9ff", MUTED = "#8e9099";
export const TERMS = {
  heiban: ["平板", "へいばん", "flat"], atamadaka: ["頭高", "あたまだか", "head-high"],
  nakadaka: ["中高", "なかだか", "middle-high"], odaka: ["尾高", "おだか", "tail-high"],
};
const NAMES = {
  heiban: "flat — rises after the first sound and stays high",
  atamadaka: "high on the first sound, then drops",
  nakadaka: "rises, then drops inside the word",
  odaka: "rises and drops right after the word",
};
const NO_ACCENT = new Set(["助詞", "助動詞", "記号"]);

export function morae(kana) {
  const out = [];
  for (const c of kana) {
    if (SMALL.has(c) && out.length) out[out.length - 1] += c;
    else out.push(c);
  }
  return out;
}

/** {reading, accent} for a token, from its dictionary form. */
export function accentOf(tok) {
  if (!tok.lookupable || NO_ACCENT.has(tok.pos)) return null;
  const list = accentEntries(tok.base).length ? accentEntries(tok.base) : accentEntries(tok.surface);
  if (!list.length) return null;
  let pick = list[0];
  if (list.length > 1 && tok.reading) {
    pick = list.find(([r]) => r === tok.reading) || list.find(([r]) => r.startsWith(tok.reading.slice(0, -1) || tok.reading)) || pick;
  }
  return { reading: pick[0], accent: pick[1][0] };
}

export function kind(tok) {
  const a = accentOf(tok);
  if (!a) return null;
  const n = a.accent, count = morae(a.reading).length;
  if (n === 0) return "heiban";
  if (n === 1) return "atamadaka";
  return n >= count ? "odaka" : "nakadaka";
}

export function wordColor(tok) {
  const k = kind(tok);
  if (k) return COLORS[k];
  if (tok.pos === "助詞" || tok.pos === "助動詞") return MUTED;
  return null;
}

function wordHighs(tok) {
  const a = accentOf(tok);
  if (!a) return null;
  const ms = morae(tok.reading || display(tok, "hiragana"));
  if (!ms.length) return null;
  const n = a.accent;
  if (n === 0) return [false, ...ms.slice(1).map(() => true)];
  return ms.map((_, i) => (n === 1 ? i === 0 : i > 0 && i < n));
}

/** Map token -> [high?] for each sound; particles follow the word before them. */
export function sentenceHighs(lines) {
  const out = new Map();
  for (const line of lines) {
    let state = null;
    for (const tok of line) {
      const h = wordHighs(tok);
      if (h) {
        out.set(tok, h);
        state = accentOf(tok).accent === 0;   // heiban stays high into its particles; others are low
        continue;
      }
      if ((tok.pos === "助詞" || tok.pos === "助動詞") && state !== null && tok.reading) {
        out.set(tok, morae(tok.reading).map(() => state));
        continue;
      }
      if (!tok.space) state = null;
    }
  }
  return out;
}

/** Reading with high sounds overlined and ꜜ at the drop (HTML). */
export function patternHTML(tok) {
  const k = kind(tok);
  if (!k) return "";
  const { reading, accent: n } = accentOf(tok);
  const ms = morae(reading);
  const highs = n === 0 ? [false, ...ms.slice(1).map(() => true)] : ms.map((_, i) => (n === 1 ? i === 0 : i > 0 && i < n));
  let html = "";
  ms.forEach((m, i) => {
    html += highs[i] ? `<span class="hi">${m}</span>` : m;
    if (n && i === n - 1) html += `<span style="color:${COLORS[k]}">ꜜ</span>`;
  });
  const t = TERMS[k];
  const dict = hasKanji(tok.surface) && tok.base !== tok.surface ? " (dictionary form)" : "";
  return `<div class="pitch"><span style="color:${COLORS[k]}">■</span> <span class="pr">${html}</span>${dict}` +
    ` <span class="muted small">${t[0]} (${t[1]}) — ${NAMES[k]}</span></div>`;
}

export function legendHTML(shown) {
  const lines = [];
  if (shown.has("japanese") || shown.has("romaji")) {
    lines.push(Object.keys(TERMS).map((k) =>
      `<span style="color:${COLORS[k]}">■</span> ${TERMS[k][0]} (${TERMS[k][1]}) “${TERMS[k][2]}”`).join("  "));
  }
  if (shown.has("furigana") || shown.has("hiragana")) {
    lines.push(`<span style="color:${HIGH}">■</span> high <span style="color:${LOW}">■</span> low ` +
      `<span class="muted">— the pitch drops where orange turns blue</span>`);
  }
  return lines.join("<br>");
}
