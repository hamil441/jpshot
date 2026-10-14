// Sentence and word difficulty on a JLPT-like scale (N5 easy … N1 hard).
import { isCommon, kanjiInfo } from "./data.js";
import { isKanji } from "./nlp.js";

const CONTENT = new Set(["名詞", "動詞", "形容詞", "副詞", "連体詞", "接続詞", "感動詞"]);
const KEIGO = new Set(["いらっしゃる", "おっしゃる", "申す", "参る", "致す", "存じる", "なさる", "くださる", "伺う",
  "召し上がる", "ござる", "いただく", "差し上げる", "申し上げる"]);
const LABELS = { 1: "Beginner", 2: "Elementary", 3: "Intermediate", 4: "Upper-intermediate", 5: "Advanced" };
export const LEVEL_COLORS = { 1: "#2fb383", 2: "#7cc04b", 3: "#f0a030", 4: "#e8743d", 5: "#e8556d" };
export const GRADIENT = ["#2fb383", "#7cc04b", "#e3c03a", "#e8743d", "#e8556d"];
export const MUTED = "#8e9099";

const blend = (v) => (v.length ? 0.6 * (v.reduce((a, b) => a + b, 0) / v.length) + 0.4 * Math.max(...v) : 1);

function kanjiHardness(info) {
  if (!info) return 5;
  if (info.jlpt) return Math.max(1, Math.min(5, 6 - info.jlpt));
  if (info.grade) return info.grade <= 6 ? 1 + 0.5 * info.grade : info.grade === 8 ? 4.5 : 5;
  return 5;
}

export async function estimate(lines) {
  const tokens = lines.flat();
  const text = tokens.map((t) => t.surface).join("");
  if (!text.trim()) return null;
  const reasons = [];
  const kanjiScores = {};
  for (const c of new Set([...text].filter(isKanji))) kanjiScores[c] = kanjiHardness(await kanjiInfo(c));
  const kVals = Object.values(kanjiScores);
  const hardK = Object.entries(kanjiScores).filter(([, h]) => h >= 4).map(([c]) => c).slice(0, 4);
  if (hardK.length) reasons.push(`advanced kanji: ${hardK.join("、")}`);
  else reasons.push(kVals.length ? `${kVals.length} kanji, all fairly basic` : "no kanji");

  const words = [...new Set(tokens.filter((t) => t.lookupable && (CONTENT.has(t.pos) || (t.pos === "名詞"))).map((t) => t.base))].slice(0, 30);
  const wordHard = {}, rare = [];
  for (const w of words) {
    const common = await isCommon(w);
    let h = common === null ? 4 : common ? 2.5 : 4.5;
    const kh = [...w].filter(isKanji).map((c) => kanjiScores[c] ?? 5);
    if (kh.length) h = Math.max(h, Math.max(...kh) - (common ? 0.5 : 0));
    wordHard[w] = h;
    if (h >= 4.5) rare.push(w);
  }
  if (rare.length) reasons.push(`less common words: ${rare.slice(0, 4).join("、")}`);

  const aux = new Set(tokens.filter((t) => t.pos === "助動詞").map((t) => t.base));
  const joins = tokens.filter((t) => t.pos === "助詞" && t.pos1 === "接続助詞").length;
  const keigo = tokens.some((t) => KEIGO.has(t.base));
  const g = Math.min(5, 1 + 0.5 * aux.size + 0.6 * joins + (keigo ? 1.2 : 0));
  const bits = [];
  if (aux.size) bits.push(`${aux.size} verb ending${aux.size > 1 ? "s" : ""}`);
  if (joins) bits.push(`${joins} linked clause${joins > 1 ? "s" : ""}`);
  if (keigo) bits.push("keigo (honorific/humble)");
  if (bits.length) reasons.push("grammar: " + bits.join(", "));
  const n = tokens.filter((t) => t.pos !== "記号" && !t.space).reduce((a, t) => a + t.surface.length, 0);
  reasons.push(`${n} characters long`);

  const score = 0.4 * blend(Object.values(wordHard)) + 0.35 * blend(kVals) + 0.15 * g + 0.1 * Math.min(5, 1 + n / 20);
  const level = Math.max(1, Math.min(5, Math.round(score)));
  return { level, jlpt: `N${6 - level}`, label: LABELS[level], score, reasons, wordHard, kanjiScores,
    stars: "★".repeat(level) + "☆".repeat(5 - level), color: LEVEL_COLORS[level] };
}

export function wordColor(d, tok) {
  if (!d) return null;
  if (tok.pos === "助詞" || tok.pos === "助動詞") return MUTED;
  if (!tok.lookupable) return null;
  let h = d.wordHard[tok.base];
  if (h === undefined) {
    const kh = [...tok.surface].filter(isKanji).map((c) => d.kanjiScores[c] ?? 5);
    h = kh.length ? Math.max(...kh) : 1;
  }
  return GRADIENT[Math.max(0, Math.min(4, Math.round(h) - 1))];
}

export function wordLevel(d, tok) {
  if (!d || d.wordHard[tok.base] === undefined) return "";
  return `N${6 - Math.max(1, Math.min(5, Math.round(d.wordHard[tok.base])))}`;
}

export function legendHTML() {
  return "word difficulty: easy " + GRADIENT.map((c) => `<span style="color:${c}">■</span>`).join("") +
    ` hard <span class="muted">(≈N5…N1)</span> · <span style="color:${MUTED}">■</span> particles/endings`;
}
