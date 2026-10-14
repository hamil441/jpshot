// Japanese tokenizing (kuromoji / IPADIC), readings, furigana and rōmaji.
export const JA_RE = /[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ々〆〇]/;
const KANJI_RE = /[㐀-鿿豈-﫿々〆]/;
const READING_FIXES = { "日本": "にほん", "日本人": "にほんじん" };

export const hasKanji = (s) => KANJI_RE.test(s || "");
export const isKanji = (c) => /[㐀-鿿豈-﫿]/.test(c);
export function kataToHira(s) {
  return (s || "").replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60));
}
const isKana = (c) => /[぀-ヿ]/.test(c);

let tokenizerPromise = null;
export function loadTokenizer(dicPath = "vendor/kuromoji/dict/") {
  if (!tokenizerPromise) {
    tokenizerPromise = new Promise((resolve, reject) => {
      if (!window.kuromoji) return reject(new Error("tokenizer script not loaded"));
      window.kuromoji.builder({ dicPath }).build((err, t) => (err ? reject(err) : resolve(t)));
    });
  }
  return tokenizerPromise;
}

/** Token shape used everywhere in the app. */
function makeToken(k) {
  const surface = k.surface_form;
  const ja = JA_RE.test(surface);
  let reading = k.reading && k.reading !== "*" ? kataToHira(k.reading) : "";
  if (!reading && ja && !hasKanji(surface)) reading = kataToHira(surface);
  if (!ja) reading = "";
  reading = READING_FIXES[surface] || reading;
  const pron = k.pronunciation && k.pronunciation !== "*" ? kataToHira(k.pronunciation) : reading;
  const base = k.basic_form && k.basic_form !== "*" ? k.basic_form : surface;
  const pos = k.pos || "";
  const isSpace = /^\s+$/.test(surface);
  return {
    surface, reading, pron, base, pos,
    pos1: k.pos_detail_1 && k.pos_detail_1 !== "*" ? k.pos_detail_1 : "",
    ctype: k.conjugated_type && k.conjugated_type !== "*" ? k.conjugated_type : "",
    cform: k.conjugated_form && k.conjugated_form !== "*" ? k.conjugated_form : "",
    lookupable: ja && pos !== "記号" && !isSpace,
    space: isSpace,
  };
}

/** text -> lines of tokens */
export function tokenize(tokenizer, text) {
  return text.split("\n").map((line) => tokenizer.tokenize(line).map(makeToken));
}

export function candidates(tok) {
  return [...new Set([tok.base, tok.surface].filter(Boolean))];
}

// -- furigana ------------------------------------------------------------------
export function furiganaParts(surface, reading) {
  let s = [...surface], r = [...reading];
  let prefix = "", suffix = "";
  while (s.length > 1 && r.length && isKana(s[s.length - 1]) && kataToHira(s[s.length - 1]) === r[r.length - 1]) {
    suffix = s.pop() + suffix; r.pop();
  }
  while (s.length > 1 && r.length && isKana(s[0]) && kataToHira(s[0]) === r[0]) {
    prefix += s.shift(); r.shift();
  }
  return [prefix, s.join(""), r.join(""), suffix];
}

/** Segments for one token: [[text, ruby]] (ruby "" when none). */
export function rubySegments(tok, knownKanji = null) {
  if (!tok.reading || !hasKanji(tok.surface)) return [[tok.surface, ""]];
  const [p, core, rc, sfx] = furiganaParts(tok.surface, tok.reading);
  if (!rc) return [[tok.surface, ""]];
  if (knownKanji && [...core].every((c) => !isKanji(c) || knownKanji.has(c))) return [[tok.surface, ""]];
  return [[p, ""], [core, rc], [sfx, ""]].filter(([t]) => t);
}

export function ankiFurigana(lines) {
  return lines.map((line) => line.map((t) => {
    if (t.reading && hasKanji(t.surface)) {
      const [p, core, rc, sfx] = furiganaParts(t.surface, t.reading);
      if (rc) return `${p} ${core}[${rc}]${sfx}`;
    }
    return t.surface;
  }).join("").trim()).join("\n");
}

// -- rōmaji -------------------------------------------------------------------------
const MONO = {};
("あa いi うu えe おo かka きki くku けke こko さsa しshi すsu せse そso たta ちchi つtsu てte とto " +
 "なna にni ぬnu ねne のno はha ひhi ふfu へhe ほho まma みmi むmu めme もmo やya ゆyu よyo " +
 "らra りri るru れre ろro わwa をo んn がga ぎgi ぐgu げge ごgo ざza じji ずzu ぜze ぞzo " +
 "だda ぢji づzu でde どdo ばba びbi ぶbu べbe ぼbo ぱpa ぴpi ぷpu ぺpe ぽpo " +
 "ぁa ぃi ぅu ぇe ぉo ゃya ゅyu ょyo ゎwa ゐi ゑe ゔvu").split(" ").forEach((x) => { MONO[x[0]] = x.slice(1); });
const DIGRAPHS = {
  "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo", "しゃ": "sha", "しゅ": "shu", "しょ": "sho", "ちゃ": "cha", "ちゅ": "chu",
  "ちょ": "cho", "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo", "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo", "みゃ": "mya",
  "みゅ": "myu", "みょ": "myo", "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo", "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
  "じゃ": "ja", "じゅ": "ju", "じょ": "jo", "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo", "びゃ": "bya", "びゅ": "byu",
  "びょ": "byo", "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo", "しぇ": "she", "じぇ": "je", "ちぇ": "che", "ふぁ": "fa",
  "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo", "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du", "うぃ": "wi",
  "うぇ": "we", "うぉ": "wo", "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo", "つぁ": "tsa", "いぇ": "ye",
};
const PUNCT = { "。": ".", "、": ",", "「": '"', "」": '"', "『": '"', "』": '"', "！": "!", "？": "?", "・": " ",
  "（": "(", "）": ")", "：": ":", "；": ";", "…": "...", "〜": "~", "　": " ", "，": ",", "．": "." };

export function toRomaji(text) {
  const s = [...kataToHira(text)];
  const out = [];
  let sokuon = false;
  for (let i = 0; i < s.length;) {
    const c = s[i];
    if (c === "っ") { sokuon = true; i++; continue; }
    let r;
    const two = s[i] + (s[i + 1] || "");
    if (DIGRAPHS[two]) { r = DIGRAPHS[two]; i += 2; }
    else if (MONO[c] !== undefined) { r = MONO[c]; i++; }
    else if (c === "ー") { const last = out[out.length - 1] || ""; r = /[aeiou]$/.test(last) ? last.slice(-1) : ""; i++; }
    else { r = PUNCT[c] ?? c; i++; }
    if (sokuon && r && /^[a-z]/.test(r) && !/^[aeiou]/.test(r)) r = (r.startsWith("ch") ? "t" : r[0]) + r;
    sokuon = false;
    if (out.length && out[out.length - 1] === "n" && r && /^[aeiouy]/.test(r)) out[out.length - 1] = "n'";
    out.push(r);
  }
  return out.join("");
}

const PARTICLE_ROMAJI = { "は": "wa", "へ": "e", "を": "o" };
export function romajiOf(tok) {
  if (tok.pos === "助詞" && PARTICLE_ROMAJI[tok.surface]) return PARTICLE_ROMAJI[tok.surface];
  if (tok.reading) {
    let r = tok.reading;
    if (r.length > 1 && /[はへ]$/.test(r) && /[わえ]$/.test(tok.pron || "")) r = r.slice(0, -1) + tok.pron.slice(-1);
    return toRomaji(r);
  }
  return hasKanji(tok.surface) ? tok.surface : toRomaji(tok.surface);
}

const OPENERS = new Set(["「", "『", "（", "(", '"']);
function romajiSpace(prev, tok) {
  if (!prev || tok.space || prev.space) return false;
  if (OPENERS.has(prev.surface)) return false;
  if (tok.pos === "記号") return OPENERS.has(tok.surface);
  if (tok.pos === "助動詞") return false;
  if (tok.pos === "名詞" && tok.pos1 === "接尾") return false;
  if (tok.pos === "動詞" && (tok.pos1 === "接尾" || tok.pos1 === "非自立") && prev.surface !== "て" && prev.surface !== "で") return false;
  if (tok.pos === "助詞" && ["て", "で", "ば"].includes(tok.surface)) return false;
  return true;
}

/** Rōmaji for every token (a trailing っ doubles the next token's first consonant). */
export function romajiMap(lines) {
  const map = new Map();
  for (const line of lines) {
    line.forEach((t, i) => {
      let r = romajiOf(t);
      const kana = t.reading || t.surface;
      if (kana.endsWith("っ") || kana.endsWith("ッ")) {
        const next = line[i + 1] ? romajiOf(line[i + 1]) : "";
        if (/^[b-df-hj-np-tv-z]/.test(next)) r += next.startsWith("ch") ? "t" : next[0];
      }
      map.set(t, r);
    });
  }
  return map;
}

/** Display text of a token in a mode: original | hiragana | romaji */
export function display(tok, mode, rmap = null) {
  if (mode === "romaji") return rmap ? rmap.get(tok) ?? romajiOf(tok) : romajiOf(tok);
  if (mode === "hiragana" && tok.reading && hasKanji(tok.surface)) return tok.reading;
  return tok.surface;
}

/** Plain text of the whole sentence in a mode, with rōmaji spacing. */
export function renderText(lines, mode) {
  const rmap = mode === "romaji" ? romajiMap(lines) : null;
  return lines.map((line) => {
    let out = "", prev = null;
    for (const t of line) {
      if (mode === "romaji" && romajiSpace(prev, t)) out += " ";
      out += display(t, mode, rmap);
      if (!t.space) prev = t;
    }
    return out;
  }).join("\n");
}

export function romajiSpacing(lines) {
  // returns Set of tokens that get a space before them in rōmaji mode
  const set = new Set();
  for (const line of lines) {
    let prev = null;
    for (const t of line) {
      if (romajiSpace(prev, t)) set.add(t);
      if (!t.space) prev = t;
    }
  }
  return set;
}

export function flatten(text, lang) {
  return text.split("\n").map((l) => l.trim()).filter(Boolean).join(lang === "ja" ? "" : " ");
}
