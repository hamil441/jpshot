// Grammar for learners (IPADIC tags from kuromoji): word roles, particles, conjugations,
// verb-phrase summaries and multi-word grammar patterns.

const ROLE = {
  noun: ["Noun", "#4e9af1", "a thing, person, place or idea"],
  pronoun: ["Pronoun", "#4e9af1", "stands in for a noun (I, you, this, that…)"],
  verb: ["Verb", "#e8556d", "an action or state"],
  iadj: ["い-adjective", "#f0a030", "describes a noun; conjugates itself (past, negative…)"],
  naadj: ["な-adjective", "#e8a33d", "describes a noun; takes な before nouns, だ/です at the end"],
  adverb: ["Adverb", "#b07ce8", "modifies a verb, adjective or the whole sentence"],
  prenoun: ["Pre-noun adjectival", "#d18a3a", "only ever comes right before a noun (この, その, ある…)"],
  conj: ["Conjunction", "#8e9aa8", "links sentences or clauses (でも, そして…)"],
  interj: ["Interjection", "#8e9aa8", "an exclamation or greeting"],
  particle: ["Particle", "#2fb383", "a small word that marks the role of what comes before it"],
  aux: ["Auxiliary", "#d65db1", "a helper attached to a verb/adjective: tense, politeness, negation…"],
  prefix: ["Prefix", "#8e9aa8", "attaches to the front of a word"],
  suffix: ["Suffix", "#7aa5c9", "attaches to the end of a word (さん, たち, 的…)"],
  symbol: ["Punctuation", "#8e9aa8", ""],
};
export const LEGEND = ["noun", "verb", "iadj", "naadj", "adverb", "particle", "aux", "suffix"];

export function role(tok) {
  const { pos, pos1 } = tok;
  if (pos === "名詞") {
    if (pos1 === "代名詞") return "pronoun";
    if (pos1 === "形容動詞語幹") return "naadj";
    if (pos1 === "接尾") return "suffix";
    return "noun";
  }
  if (pos === "動詞") return pos1 === "接尾" ? "suffix" : "verb";
  if (pos === "形容詞") return "iadj";
  if (pos === "副詞") return "adverb";
  if (pos === "連体詞") return "prenoun";
  if (pos === "接続詞") return "conj";
  if (pos === "感動詞" || pos === "フィラー") return "interj";
  if (pos === "助詞") return "particle";
  if (pos === "助動詞") return "aux";
  if (pos === "接頭詞") return "prefix";
  return "symbol";
}

export function colorFor(tok) {
  if (!tok.lookupable) return null;
  return ROLE[role(tok)][1];
}

export function legendHTML() {
  return LEGEND.map((k) => `<span style="color:${ROLE[k][1]}">■</span> ${ROLE[k][0]}`).join("  ") +
    "  · plain = symbols, numbers, non-Japanese";
}

const PARTICLES = {
  "は": "Topic marker (read “wa”): what the sentence is about — “as for X…”",
  "が": "Subject marker: who/what does the action or has the quality; also “but” between clauses",
  "を": "Direct-object marker (read “o”): what the action is done to",
  "に": "Target / time / place of existence: to, at, in, on (a time), for",
  "で": "Place of action, or means: at/in (where it happens), by/with (how)",
  "へ": "Direction marker (read “e”): toward",
  "と": "“and” (complete list), “with” (together), or quotation “that…”",
  "の": "Possessive / linking (“X's”, “X of Y”), or turns a clause into a noun",
  "も": "“also / too”; with numbers or negatives “even, as many as”",
  "か": "Question marker; between nouns “or”",
  "から": "“from” (starting point), or after a clause “because”",
  "まで": "“until / up to / as far as”",
  "より": "“than” (comparison) or formal “from”",
  "や": "“and” for a non-complete list (… and so on)",
  "ね": "Sentence end: seeks agreement — “right? / isn't it?”",
  "よ": "Sentence end: emphasis / telling new information — “you know”",
  "て": "Te-form connector: “and (then)”, or links to a helper verb (〜ている, 〜てください…)",
  "ば": "Conditional: “if …”",
  "けど": "“but / although” (casual)", "けれど": "“but / although”", "けれども": "“but / although” (polite)",
  "のに": "“even though / despite” (often with frustration)", "ので": "“because / so” (softer, explanatory)",
  "し": "Lists reasons: “and also… (so)”", "たり": "Lists example actions: “do things like … and …”",
  "ながら": "“while (doing)” — two actions at once", "でも": "“even / or something”", "だけ": "“only / just”",
  "しか": "“only / nothing but” (always with a negative verb)", "ばかり": "“nothing but / just (did)”",
  "など": "“etc. / things like”", "って": "Casual quotation or topic: “(they said) that… / speaking of…”",
  "な": "Sentence end after a dictionary-form verb: prohibition “don't!”; otherwise emotive",
  "わ": "Sentence end: soft emphasis", "ぞ": "Sentence end: strong emphasis", "さ": "Sentence end: casual assertion",
  "ほど": "“to the extent of / about”", "くらい": "“about / at least”", "ぐらい": "“about / at least”",
  "とか": "“things like / or something”", "かな": "Sentence end: “I wonder…”",
};
const AUX = {
  "た": ["past", "Past / completed — “did”"], "ます": ["polite", "Polite ending (〜ます)"],
  "です": ["polite", "Polite copula “is / am / are” (です)"], "だ": ["copula", "Plain copula “is / am / are” (だ)"],
  "ない": ["negative", "Negative — “not”"], "ぬ": ["negative", "Negative (formal: ぬ, ず, ん in ません)"],
  "ん": ["negative", "Negative (ん, as in ません)"],
  "たい": ["want", "Desire — “want to …”"], "れる": ["passive", "Passive / potential / honorific (れる)"],
  "られる": ["passive", "Passive / potential / honorific (られる)"], "せる": ["causative", "Causative — “make/let someone …”"],
  "させる": ["causative", "Causative — “make/let someone …”"], "う": ["volitional", "Volitional — “let's … / I'll …”"],
  "よう": ["volitional", "Volitional — “let's … / I'll …”"], "まい": ["neg-volitional", "“will not / probably not”"],
  "らしい": ["hearsay", "“seems / apparently”"], "そうだ": ["hearsay", "“looks like / I heard that”"],
};
const TE_HELPERS = {
  "いる": ["progressive", "〜ている: ongoing action (“is …ing”) or resulting state"],
  "ある": ["resultant", "〜てある: something was done and remains that way"],
  "しまう": ["completive", "〜てしまう: finish completely / do by mistake (regret)"],
  "おく": ["preparatory", "〜ておく: do in advance / leave as is"],
  "みる": ["attempt", "〜てみる: try doing and see"], "くる": ["come", "〜てくる: come to / start to"],
  "いく": ["go", "〜ていく: continue on / go on doing"], "くれる": ["favor-to-me", "〜てくれる: someone does it for me"],
  "もらう": ["receive-favor", "〜てもらう: have someone do it for me"], "あげる": ["favor-to-other", "〜てあげる: do it for someone"],
  "くださる": ["request", "〜てください: please do"], "ちゃう": ["completive", "〜ちゃう: casual 〜てしまう"],
};
const CTYPE = [["五段", "godan verb (う-verb): the ending changes across a-i-u-e-o"],
  ["一段", "ichidan verb (る-verb): drop る to conjugate"], ["カ変", "irregular verb (来る)"],
  ["サ変", "irregular verb (する)"], ["形容詞", "い-adjective"]];
const CFORM = [["基本形", "dictionary (plain, sentence-ending) form"], ["連用", "continuative stem — joins ます, た, て, たい…"],
  ["未然", "negative base — joins ない, (よ)う, れる…"], ["仮定", "conditional base — joins ば"],
  ["命令", "imperative — a command"], ["体言接続", "attributive — modifies the noun after it"]];
const LABELS = { past: "past", polite: "polite", negative: "negative", want: "want to", passive: "passive/potential",
  causative: "causative", volitional: "volitional", progressive: "ongoing (〜ている)", te: "te-form (connecting)",
  conditional: "conditional", completive: "completed (〜てしまう)", attempt: "try (〜てみる)", request: "request (〜ください)",
  copula: "plain “is”", resultant: "resultant state", preparatory: "in advance" };

function attaches(prev, tok) {
  if (tok.pos === "助動詞") return prev.pos !== "記号";
  if (tok.pos === "動詞" && tok.pos1 === "接尾" && ["動詞", "形容詞", "助動詞"].includes(prev.pos)) return true;
  if (tok.pos === "助詞" && ["て", "で", "ば"].includes(tok.surface) && ["動詞", "形容詞", "助動詞"].includes(prev.pos)) return true;
  if (tok.pos === "動詞" && tok.pos1 === "非自立" && ["て", "で"].includes(prev.surface)) return true;
  if (tok.pos === "形容詞" && tok.pos1 === "非自立" && ["動詞", "形容詞"].includes(prev.pos)) return true;
  return false;
}
const joinsSuru = (line, k) => k > 0 && k < line.length && line[k].base === "する" && line[k - 1].pos === "名詞";

function phraseOf(line, i) {
  let s = i;
  while (s > 0 && (attaches(line[s - 1], line[s]) || joinsSuru(line, s))) s--;
  let e = s + 1;
  while (e < line.length && (attaches(line[e - 1], line[e]) || joinsSuru(line, e))) e++;
  return e - s === 1 ? [i, i + 1] : [s, e];
}

function summarize(toks) {
  const flags = [];
  const add = (f) => { if (!flags.includes(f)) flags.push(f); };
  toks.forEach((t, j) => {
    if (t.pos === "助動詞" && AUX[t.base]) add(AUX[t.base][0]);
    else if (t.pos === "助詞" && ["て", "で"].includes(t.surface) && j === toks.length - 1) add("te");
    else if (t.pos === "助詞" && t.surface === "ば") add("conditional");
    else if (j > 0 && ["て", "で"].includes(toks[j - 1].surface) && TE_HELPERS[t.base]) add(TE_HELPERS[t.base][0]);
    else if (t.pos === "形容詞" && t.base === "ない" && j > 0) add("negative");
  });
  const head = toks[0];
  const tense = flags.includes("past") ? "past" : (flags.some((f) => ["te", "volitional", "request"].includes(f)) ? "" : "present");
  const parts = (tense ? [tense] : []).concat(flags.filter((f) => f !== "past").map((f) => LABELS[f] || f));
  if (!flags.includes("polite") && ["動詞", "形容詞"].includes(head.pos) && tense) parts.push("plain");
  return parts.join(" · ");
}

export function describe(lines, tok) {
  const r = role(tok);
  const [name, color, note] = ROLE[r];
  const info = { role: name, color, note, details: [], phrase: "", summary: "" };
  if (tok.pos === "助詞") {
    let expl = PARTICLES[tok.surface];
    if (tok.surface === "が" && tok.pos1 === "接続助詞") expl = "“but” — joins two clauses";
    if (tok.surface === "で" && tok.pos1 === "接続助詞") expl = PARTICLES["て"];
    if (expl) info.details.push(expl);
  } else if (tok.pos === "助動詞" && AUX[tok.base]) {
    info.details.push(AUX[tok.base][1]);
  } else if (tok.pos === "動詞" || tok.pos === "形容詞") {
    const ct = CTYPE.find(([k]) => tok.ctype.includes(k));
    if (ct) info.details.push(`Type: ${ct[1]}`);
    if (tok.pos1 === "非自立" && TE_HELPERS[tok.base]) info.details.push(TE_HELPERS[tok.base][1]);
  }
  if (tok.cform && ["動詞", "形容詞", "助動詞"].includes(tok.pos)) {
    const cf = CFORM.find(([k]) => tok.cform.includes(k));
    if (cf) info.details.push(`Form: ${tok.cform} — ${cf[1]}`);
  }
  for (const line of lines) {
    const i = line.indexOf(tok);
    if (i < 0) continue;
    const [s, e] = phraseOf(line, i);
    if (e - s > 1 || ["動詞", "形容詞"].includes(line[s].pos)) {
      const toks = line.slice(s, e);
      info.phrase = toks.map((t) => t.surface).join("");
      info.summary = summarize(toks);
    }
    break;
  }
  return info;
}

export function describeHTML(info) {
  let h = `<div class="role"><span class="tag" style="background:${info.color}">${info.role}</span>` +
    (info.note ? ` <span class="muted">${info.note}</span>` : "") + "</div>";
  for (const d of info.details) h += `<div>• ${esc(d)}</div>`;
  if (info.phrase && info.summary) {
    h += `<div>Phrase <b>${esc(info.phrase)}</b>: <span style="color:#d65db1">${esc(info.summary)}</span></div>`;
  }
  return h;
}

// -- multi-word grammar patterns -------------------------------------------------------------
const END = "(?=[。、！？!?\\s」』]|$)";
const P = (id, regex, form, meaning, jlpt, opts = {}) => ({ id, regex: regex && new RegExp(regex, "g"), form, meaning, jlpt, boundary: true, ...opts });
export const PATTERNS = [
  P("wakedewanai", "わけ(では|じゃ)(ない|なかった|ありません|ねえ)", "〜わけではない", "it's not that… / it doesn't mean that…", "N3"),
  P("wakeganai", "わけ(が|は)ない", "〜わけがない", "there's no way that…", "N3"),
  P("wakeda", "わけ(だ|です|か|で)", "〜わけだ", "that's why… / so it means… / no wonder", "N3"),
  P("teshimau", "(て|で)しま[うっいわえお]|ちゃ[うっいわお]|じゃ[うっいわお]", "〜てしまう / 〜ちゃう", "do completely, or by accident / with regret", "N4"),
  P("nakereba", "なければ(なら|いけ)|なきゃ|なくては(なら|いけ)|なくちゃ|ないと(いけ|だめ|ダメ)", "〜なければならない", "must / have to", "N4"),
  P("temoii", "(て|で)も(いい|良い|かまわ|構わ)", "〜てもいい", "it's okay to… / may…", "N5"),
  P("tewaikenai", "(て|で)は(いけ|だめ|ダメ|なら)|ちゃ(いけ|だめ|ダメ)", "〜てはいけない", "must not…", "N5"),
  P("takotogaaru", "(た|だ)ことが(ある|あり|ない|なかっ)", "〜たことがある", "have (ever) done…", "N4"),
  P("kotogadekiru", "ことが(でき|出来)", "〜ことができる", "can / be able to…", "N4"),
  P("tsumori", "つもり", "〜つもり", "intend to / plan to…", "N4"),
  P("hazu", "はず", "〜はずだ", "should be / is expected to (by logic)", "N3"),
  P("kamoshirenai", "かもしれ|かも" + END, "〜かもしれない", "might / maybe", "N4"),
  P("darou", "でしょう|だろう", "〜でしょう / だろう", "probably… / …right?", "N4"),
  P("souda", "そう(だ|です|な|に)", "〜そうだ", "looks like… (appearance) or I hear that… (hearsay)", "N4"),
  P("rashii", "らしい", "〜らしい", "apparently / seems; or typical of", "N3"),
  P("mitai", "みたい", "〜みたい", "seems like / like (casual)", "N4"),
  P("youni", "ように(する|し|なる|なっ)", "〜ようにする / ようになる", "make sure to… / come to (be able to)…", "N4"),
  P("youda", "よう(だ|です|な|に)", "〜ようだ / ような / ように", "seems / like… / so that…", "N4"),
  P("kotoni", "ことに(する|し|なる|なっ)", "〜ことにする / ことになる", "decide to… / it's been decided that…", "N4"),
  P("tameni", "ために|ため" + END, "〜ために", "in order to… / because of…", "N4"),
  P("nagara", "ながら", "〜ながら", "while (doing)…", "N4"),
  P("tekara", "(て|で)から", "〜てから", "after doing…", "N5"),
  P("node", "ので", "〜ので", "because / so (explaining)", "N4"),
  P("noni", "のに", "〜のに", "even though / despite (often frustrated)", "N4"),
  P("tara", "(た|だ)ら(?!い)", "〜たら", "if / when (once…)", "N4"),
  P("ba", "(え|け|せ|て|ね|べ|め|れ|げ)ば(?!かり)", "〜ば", "if… (conditional)", "N4", { boundary: false }),
  P("nara", "なら", "〜なら", "if it's… / as for…", "N4"),
  P("bakari", "ばかり", "〜ばかり", "nothing but… / just (did)", "N4"),
  P("shikanai", "しか.{0,12}?(ない|ません|なかった)", "〜しか〜ない", "only… (with a negative verb)", "N4"),
  P("dake", "だけ", "〜だけ", "only / just", "N5"),
  P("sugiru", "すぎ|過ぎ", "〜すぎる", "too much…", "N4"),
  P("yasui", "(やす|にく|づら)(い|く|かっ)", "〜やすい / にくい", "easy to… / hard to…", "N4"),
  P("tekureru", "(て|で)(くれ|くださ|下さ)", "〜てくれる / てください", "someone does it for me / please do…", "N5"),
  P("temorau", "(て|で)(もら|いただ|頂)", "〜てもらう", "have someone do it (for me)", "N4"),
  P("teageru", "(て|で)(あげ|さしあげ)", "〜てあげる", "do it for someone", "N4"),
  P("temiru", "(て|で)み(る|た|ます|よう|て)", "〜てみる", "try doing and see", "N4"),
  P("teoku", "(て|で)お(く|い|き|こ)", "〜ておく", "do in advance / leave it as is", "N4"),
  P("toshite", "として", "〜として", "as… (a role or capacity)", "N3"),
  P("nitsuite", "について", "〜について", "about / concerning", "N3"),
  P("niyotte", "によって|による|により", "〜によって", "by (means / agent); depending on", "N3"),
  P("tte", null, "〜って", "casual quotation: “(someone says) that…” / “speaking of…”", "N3",
    { check: (t) => t.surface === "って" && t.pos === "助詞" }),
  P("tari", "(た|だ)り.{0,20}?(た|だ)り(する|し)", "〜たり〜たりする", "do things like… and…", "N4"),
  P("mama", "まま", "〜まま", "as it is / still (unchanged)", "N3"),
  P("tokoro", "ところ(だ|です|で|に)", "〜ところ", "about to / in the middle of / just did", "N4"),
  P("beki", "べき", "〜べき", "should / ought to", "N3"),
  P("zuni", "ずに", "〜ずに", "without doing… (formal)", "N3"),
  P("naide", "ないで", "〜ないで", "without doing… / please don't…", "N4"),
  P("nasai", "なさい", "〜なさい", "do…! (firm command)", "N5"),
  P("masenka", "ませんか", "〜ませんか", "won't you…? (invitation)", "N5"),
  P("mashou", "ましょう", "〜ましょう", "let's…", "N5"),
  P("janaika", "じゃないか|じゃん" + END, "〜じゃないか / じゃん", "isn't it? / you know (seeking agreement)", "N3"),
  P("janai", "じゃない|ではない|じゃありません|ではありません", "じゃない / ではない", "is not…", "N5"),
  P("kana", "かな" + END, "〜かな", "I wonder…", "N4"),
  P("noda", "(の|ん)(だ|です|ですか|か)" + END, "〜のだ / んです", "explaining or emphasizing (“the thing is…”)", "N4"),
  P("hoshii", "ほしい|欲しい", "〜ほしい / てほしい", "want (something / someone to do)", "N4"),
  P("hougaii", "(ほう|方)が(いい|良い)", "〜ほうがいい", "had better… / it's better to…", "N4"),
  P("maeni", "前に|まえに", "〜前に", "before…", "N5"),
  P("atode", "後で|あとで", "〜後で", "after…", "N5"),
  P("toomou", "と(思|おも)", "〜と思う", "I think that…", "N4"),
  P("toiu", "という|っていう|と言う", "〜という", "called… / that says… (quoting)", "N4"),
  P("youtosuru", "(よ)?うと(する|し)", "〜ようとする", "try to… / be about to…", "N3"),
];

export function detectPatterns(lines) {
  const found = [];
  lines.forEach((line, li) => {
    const starts = [];
    let text = "";
    for (const t of line) { starts.push(text.length); text += t.surface; }
    const ends = starts.map((s, i) => s + line[i].surface.length);
    const tokensFor = (a, b) => {
      const idx = starts.map((s, i) => i).filter((i) => ends[i] > a && starts[i] < b);
      return idx.length ? [idx[0], idx[idx.length - 1]] : null;
    };
    const cands = [];
    for (const p of PATTERNS) {
      if (p.check) {
        line.forEach((t, i) => { if (p.check(t)) cands.push([starts[i], ends[i], p]); });
        continue;
      }
      p.regex.lastIndex = 0;
      let m;
      while ((m = p.regex.exec(text))) {
        if (m[0].length && (!p.boundary || starts.includes(m.index))) cands.push([m.index, m.index + m[0].length, p]);
        if (!m[0].length) p.regex.lastIndex++;
      }
    }
    cands.sort((a, b) => (b[1] - b[0]) - (a[1] - a[0]) || a[0] - b[0]);
    const taken = [];
    for (const [a, b, p] of cands) {
      if (taken.some(([ta, tb]) => a < tb && b > ta)) continue;
      const span = tokensFor(a, b);
      if (span) { taken.push([a, b]); found.push({ pattern: p, line: li, first: span[0], last: span[1], text: text.slice(a, b) }); }
    }
  });
  return found.sort((x, y) => x.line - y.line || x.first - y.first);
}

export function patternsFor(matches, lines, tok) {
  return matches.filter((m) => lines[m.line] && lines[m.line].slice(m.first, m.last + 1).includes(tok));
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export { esc };
