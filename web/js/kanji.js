// Kanji breakdown: colored parts (KanjiVG), keyword/meanings/readings, origin, words sharing the kanji,
// short explanations, and an animated stroke-order view.
import { kanjiInfo, wordsWith } from "./data.js";
import { esc } from "./grammar.js";
import { isKanji } from "./nlp.js";
import { hasWriter, local, setLocal, shortExplanation } from "./services.js";

export const PART_COLORS = ["#e8556d", "#3b8fe8", "#2fb383", "#f0a030", "#a46ee0", "#d65db1"];
const OTHER = "#9aa0a6";
const KVG = "http://kanjivg.tagaini.net";
const POSITION = { left: "on the left", right: "on the right", top: "on top", bottom: "at the bottom",
  tare: "draped over the top-left", tarec: "inside", nyo: "under the bottom-left", nyoc: "inside",
  kamae: "around the outside", kamaec: "inside" };
const RADICALS = { "亻": "person", "氵": "water", "扌": "hand", "艹": "flowers", "忄": "heart", "辶": "road",
  "阝": "village / hill", "犭": "beast", "礻": "altar", "衤": "clothes", "宀": "roof", "冖": "cover", "灬": "fire",
  "刂": "sword", "亠": "lid", "儿": "legs", "冂": "hood", "勹": "wrap", "匕": "spoon", "厂": "cliff", "广": "dotted cliff",
  "尸": "corpse / flag", "彳": "going person", "疒": "sickness", "攵": "strike", "夂": "walking legs", "彡": "hair",
  "罒": "net", "⺮": "bamboo", "糸": "thread", "言": "say", "金": "metal", "食": "eat", "飠": "eat", "月": "moon / flesh",
  "日": "sun / day", "口": "mouth", "木": "tree", "火": "fire", "土": "soil", "心": "heart", "女": "woman", "子": "child",
  "人": "person", "手": "hand", "目": "eye", "田": "rice field", "力": "power", "刀": "sword", "王": "king", "石": "stone",
  "示": "show", "禾": "grain", "立": "stand", "耳": "ear", "虫": "insect", "見": "see", "貝": "shell / money", "車": "car",
  "門": "gate", "隹": "bird", "頁": "head", "大": "big", "小": "small", "山": "mountain", "川": "river", "工": "craft",
  "弓": "bow", "戈": "halberd", "斤": "axe", "方": "direction", "止": "stop", "水": "water", "米": "rice", "矢": "arrow",
  "又": "again / hand", "十": "ten", "一": "one", "二": "two", "八": "eight", "寸": "inch", "夕": "evening", "文": "writing",
  "白": "white", "皿": "dish", "羊": "sheep", "衣": "garment", "足": "foot", "走": "run", "雨": "rain", "馬": "horse",
  "魚": "fish", "鳥": "bird", "牛": "cow", "犬": "dog", "竹": "bamboo", "肉": "meat", "自": "self", "舌": "tongue" };

const svgCache = {};
async function kanjiVG(ch) {
  if (ch in svgCache) return svgCache[ch];
  const name = ch.codePointAt(0).toString(16).padStart(5, "0");
  svgCache[ch] = fetch(`https://cdn.jsdelivr.net/gh/KanjiVG/kanjivg@master/kanji/${name}.svg`)
    .then((r) => (r.ok ? r.text() : null)).catch(() => null);
  return svgCache[ch];
}

/** Parse KanjiVG: parts with positions + an SVG element with each part's strokes colored. */
export function splitKanjiVG(text, ch) {
  const clean = text.replace(/<!DOCTYPE[\s\S]*?\]>/, "");
  const doc = new DOMParser().parseFromString(clean, "image/svg+xml");
  const svg = doc.documentElement;
  if (!svg || svg.nodeName !== "svg") return null;
  svg.querySelectorAll("[id^='kvg:StrokeNumbers']").forEach((g) => g.remove());
  const attr = (el, a) => el.getAttributeNS(KVG, a) || el.getAttribute(`kvg:${a}`);
  const top = [...svg.querySelectorAll("g")].find((g) => attr(g, "element") === ch);
  if (!top) return null;
  const parts = [], seen = new Map(), loose = [];
  const walk = (g, pos) => {
    for (const child of g.children) {
      if (child.nodeName === "g") {
        const el = attr(child, "element"), p = attr(child, "position") || pos;
        if (el && el !== ch) {
          if (!seen.has(el)) { seen.set(el, parts.length); parts.push({ el, pos: p, paths: [] }); }
          parts[seen.get(el)].paths.push(...child.querySelectorAll("path"));
        } else walk(child, p);
      } else if (child.nodeName === "path") loose.push(child);
    }
  };
  walk(top, "");
  parts.forEach((p, i) => p.paths.forEach((path) => path.setAttribute("style", `stroke:${PART_COLORS[i % PART_COLORS.length]}`)));
  loose.forEach((path) => path.setAttribute("style", `stroke:${parts.length ? OTHER : PART_COLORS[0]}`));
  svg.querySelectorAll("g[style]").forEach((g) => g.setAttribute("style", g.getAttribute("style").replace(/stroke-width:[\d.]+/, "stroke-width:4")));
  svg.removeAttribute("width"); svg.removeAttribute("height");
  return { parts: parts.map(({ el, pos }) => ({ el, pos })), svg: new XMLSerializer().serializeToString(svg) };
}

const ORIGIN_KINDS = [["phono-semantic", "sound + meaning"], ["ideogrammatic compound", "meanings combined"],
  ["ideogrammic compound", "meanings combined"], ["compound ideogram", "meanings combined"], ["pictogram", "picture"],
  ["ideogram", "symbol"], ["shinjitai", "simplified form"], ["simplified from", "simplified form"]];
export const originKind = (o) => (ORIGIN_KINDS.find(([k]) => (o || "").toLowerCase().includes(k)) || [, ""])[1];

async function origin(ch) {
  const cache = local("jpshot.origins", {});
  if (ch in cache) return cache[ch];
  let text = "";
  try {
    const api = "https://en.wiktionary.org/w/api.php?origin=*&format=json&formatversion=2&action=parse&page=" + encodeURIComponent(ch);
    const secs = (await (await fetch(api + "&prop=sections")).json()).parse?.sections || [];
    const sec = secs.find((s) => (s.line || "").trim().toLowerCase() === "glyph origin");
    if (sec) {
      const html = (await (await fetch(api + `&prop=text&section=${sec.index}&disableeditsection=1`)).json()).parse?.text || "";
      const d = new DOMParser().parseFromString(html, "text/html");
      d.querySelectorAll("table, sup, style, h1, h2, h3, h4, h5, .mw-collapsible, .NavFrame").forEach((n) => n.remove());
      let t = d.body.textContent.replace(/\[\s*edit\s*\]/g, " ").replace(/\([^()]*\b(?:OC|MC|Baxter|Zhengzhang)\b[^()]*\)/g, "")
        .replace(/\(\s*[　-ヿ㐀-鿿／/,，、\s]*\)/g, "").replace(/\s+/g, " ").replace(/\s+([,.;:)])/g, "$1").trim();
      let out = "";
      for (const s of t.split(/(?<=[.!?])\s+/).slice(0, 2)) { if (out && out.length + s.length > 220) break; out = (out + " " + s).trim(); }
      text = out;
    }
  } catch (_) { return ""; }
  cache[ch] = text;
  setLocal("jpshot.origins", cache);
  return text;
}

async function keyword(ch) {
  const cache = local("jpshot.heisig", {});
  if (ch in cache) return cache[ch];
  try {
    const d = await (await fetch(`https://kanjiapi.dev/v1/kanji/${encodeURIComponent(ch)}`)).json();
    cache[ch] = d.heisig_en || "";
  } catch (_) { return ""; }
  setLocal("jpshot.heisig", cache);
  return cache[ch];
}

function layoutSentence(k) {
  if (!k.parts.length) return "";
  const items = k.parts.map((p) => [`${p.meaning || "part"} (${p.el})`, POSITION[p.pos] || ""].filter(Boolean).join(" "));
  const body = items.length === 1 ? items[0] : items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
  return body[0].toUpperCase() + body.slice(1) + ` → ${k.keyword}.`;
}
function fallbackStory(k) {
  const kind = originKind(k.origin);
  if (kind === "meanings combined" || kind === "picture") {
    const body = k.origin.replace(/^[^:]*(compound|gram)[^:]*:\s*|^(Pictogram|Ideogram)\s*[–:-]\s*/i, "");
    const first = body.split(/(?<=[.!?])\s+/)[0];
    if (first && first.length <= 160) return first;
  }
  return layoutSentence(k);
}

/** Everything for one kanji (fast parts first; online extras fill in). */
export async function info(ch, exclude = "") {
  const base = (await kanjiInfo(ch)) || { char: ch, meanings: [], on: [], kun: [] };
  const k = { ...base, keyword: "", parts: [], svg: "", origin: "", family: [], story: "", storyAI: false };
  const [vg, kw, org, fam] = await Promise.all([kanjiVG(ch), keyword(ch), origin(ch), wordsWith(ch, exclude)]);
  if (vg) {
    const split = splitKanjiVG(vg, ch);
    if (split) {
      k.svg = split.svg;
      for (const p of split.parts) {
        const pi = await kanjiInfo(p.el);
        p.meaning = RADICALS[p.el] || (pi && pi.meanings[0]) || (await keyword(p.el)) || "";
      }
      k.parts = split.parts;
    }
  }
  k.keyword = kw || k.meanings[0] || "";
  k.origin = org;
  k.family = fam;
  k.story = fallbackStory(k);
  return k;
}

export function kanjiPrompt(k) {
  const parts = k.parts.map((p) => `${p.el} = '${p.meaning || "?"}'${POSITION[p.pos] ? ", " + POSITION[p.pos] : ""}`).join("; ") ||
    "no separate parts (a basic picture/symbol)";
  return `Kanji ${k.char}, meaning "${k.keyword}". Parts: ${parts}. Origin (use only if it helps): ${k.origin || "unknown"}\n\n` +
    "In ONE short sentence (under 20 words), say why these parts mean this, as a vivid image a learner will remember. " +
    "Name parts by meaning with the character in parentheses. If a part only gives the sound, ignore it. No preamble, no quotes, no markdown.";
}
export function wordPrompt(word, reading, meaning, infos) {
  const kanji = infos.map((k) => `${k.char} = '${k.keyword}' (also: ${k.meanings.slice(0, 4).join(", ")})`).join("; ");
  return `Japanese word ${word}${reading ? ` (${reading})` : ""} means "${meaning || "?"}". Kanji: ${kanji}.\n\n` +
    "In at most 2 short sentences (under 30 words total), show how the kanji meanings combine into the word's meaning, " +
    "memorably. No preamble, no quotes, no markdown.";
}
export const writeKanji = (k) => shortExplanation(`kanji1|${k.char}`, kanjiPrompt(k), 1);
export const writeWord = (w, r, m, infos) => shortExplanation(`word2|${w}`, wordPrompt(w, r, m, infos), 2);
export { hasWriter };

export function kanjiHTML(k, { pending = false } = {}) {
  const tags = [k.strokes && `${k.strokes} strokes`, k.jlpt && `JLPT N${k.jlpt}`, originKind(k.origin)].filter(Boolean).join(" · ");
  const pic = k.svg ? `<div class="kpic">${k.svg}</div>` : `<div class="kpic kchar">${esc(k.char)}</div>`;
  const parts = k.parts.map((p, i) => `<span style="color:${PART_COLORS[i % PART_COLORS.length]}"><b>${esc(p.el)}</b></span>` +
    (p.meaning ? ` <i class="muted">${esc(p.meaning)}</i>` : "")).join(" + ");
  const rd = [k.on.length && "on " + k.on.slice(0, 3).join("、"), k.kun.length && "kun " + k.kun.slice(0, 3).join("、")].filter(Boolean).join(" · ");
  let h = `<div class="kanji"><div class="krow">${pic}<div>` +
    `<b class="kw">${esc(k.keyword)}</b> <span class="muted small">${esc(tags)}</span>` +
    (k.svg ? ` <a class="small" data-strokes="${esc(k.char)}">✍ strokes</a>` : "") +
    (parts ? `<div>${parts}</div>` : "") + (rd ? `<div class="muted small">${esc(rd)}</div>` : "") + "</div></div>";
  if (k.family.length) {
    h += `<div class="small"><b>Words with ${esc(k.char)}:</b> ` +
      k.family.map((w) => `${esc(w.word)} <span class="muted">(${esc(w.reading)})</span> ${esc(w.gloss)}`).join(" · ") + "</div>";
  }
  if (pending) h += `<div><b>Why:</b> <i class="story">✍ writing…</i></div>`;
  else if (k.story) h += k.storyAI ? `<div><b>Why:</b> <span class="story">${esc(k.story)}</span></div>` : `<div class="muted">${esc(k.story)}</div>`;
  return h + "</div>";
}

/** Animated stroke order (SVG stroke-dash animation). */
export function strokeOrderHTML(k) {
  const doc = new DOMParser().parseFromString(k.svg, "image/svg+xml");
  const paths = [...doc.querySelectorAll("path")];
  paths.forEach((p, i) => {
    p.setAttribute("class", "stroke");
    p.setAttribute("style", `${p.getAttribute("style") || ""};animation-delay:${(i * 0.7).toFixed(1)}s`);
    p.setAttribute("pathLength", "1");
  });
  return new XMLSerializer().serializeToString(doc.documentElement);
}

export const kanjiOf = (word) => [...new Set([...word].filter(isKanji))];
