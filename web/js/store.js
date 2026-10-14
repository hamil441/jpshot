// Known words (manual marks + Anki sync + imported lists) and capture history (IndexedDB).
import { hasKanji, isKanji, kataToHira } from "./nlp.js";
import { local, setLocal } from "./services.js";

const CONTENT = new Set(["名詞", "動詞", "形容詞", "副詞", "連体詞", "接続詞", "感動詞"]);
const TAGS = /<[^>]+>|\[[^\]]*\]|&nbsp;|\{\{c\d+::|\}\}/g;
const JP = /[぀-ヿ㐀-鿿々〆]/;
const READING_FIELDS = ["word furigana", "word reading", "vocabulary-furigana", "vocabulary-kana", "furigana", "reading", "kana"];

export const cleanField = (v) => v.replace(TAGS, "").replace(/\s+/g, "").trim();
export function readingFromFurigana(v) {
  const r = kataToHira(v.replace(/<[^>]+>|&nbsp;/g, "").replace(/\s*([^\s[\]]+?)\[([^\]]+)\]/g, "$2").replace(/\s/g, ""));
  return /^[぀-ゟー]+$/.test(r) ? r : "";
}

export const known = {
  data: local("jpshot.known", { known: [], unknown: [], anki: [], ankiKana: [], lastSync: "" }),
  _sets: null,
  sets() {
    if (!this._sets) {
      const d = this.data;
      this._sets = { known: new Set(d.known), unknown: new Set(d.unknown), anki: new Set(d.anki), kana: new Set(d.ankiKana) };
    }
    return this._sets;
  },
  save() { this._sets = null; setLocal("jpshot.known", this.data); },
  counts: (t) => t.lookupable && (CONTENT.has(t.pos) || (t.pos === "名詞")),
  isKnown(t) {
    const s = this.sets();
    const keys = [t.base, t.surface].filter(Boolean);
    if (keys.some((k) => s.unknown.has(k))) return false;
    if (keys.some((k) => s.known.has(k) || s.anki.has(k))) return true;
    if (!hasKanji(t.surface)) return keys.some((k) => s.kana.has(kataToHira(k)));
    return false;
  },
  total() { const s = this.sets(); return new Set([...s.known, ...s.anki].filter((w) => !s.unknown.has(w))).size; },
  toggle(t) {
    const key = t.base || t.surface, d = this.data;
    const now = !this.isKnown(t);
    d.known = d.known.filter((w) => w !== key); d.unknown = d.unknown.filter((w) => w !== key);
    (now ? d.known : d.unknown).push(key);
    this.save();
    return now;
  },
  unknownWords(lines) {
    const seen = new Set(), out = [];
    for (const t of lines.flat()) if (this.counts(t) && !this.isKnown(t) && !seen.has(t.base)) { seen.add(t.base); out.push(t); }
    return out;
  },
  knownKanji() {
    const s = this.sets();
    return new Set([...s.known, ...s.anki].flatMap((w) => [...w].filter(isKanji)));
  },
  importList(text) {
    const words = text.split(/[\n,\t;]+/).map((w) => cleanField(w)).filter((w) => w && JP.test(w) && w.length <= 20);
    const d = this.data;
    d.known = [...new Set([...d.known, ...words])];
    this.save();
    return words.length;
  },
  setAnki(words, kana) {
    this.data.anki = [...words]; this.data.ankiKana = [...kana];
    this.data.lastSync = new Date().toLocaleString();
    this.save();
  },
};

// -- history ---------------------------------------------------------------------------------
let dbp = null;
function db() {
  if (!dbp) {
    dbp = new Promise((res, rej) => {
      const r = indexedDB.open("jpshot", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("captures", { keyPath: "id" });
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  }
  return dbp;
}
async function tx(mode, fn) {
  const d = await db();
  return new Promise((res, rej) => {
    const t = d.transaction("captures", mode);
    const out = fn(t.objectStore("captures"));
    t.oncomplete = () => res(out && out.result !== undefined ? out.result : out);
    t.onerror = () => rej(t.error);
  });
}
export const history = {
  add: (cap) => tx("readwrite", (s) => s.put(cap)).catch(() => null),
  all: () => tx("readonly", (s) => s.getAll()).then((r) => (r || []).sort((a, b) => b.time - a.time)).catch(() => []),
  remove: (id) => tx("readwrite", (s) => s.delete(id)).catch(() => null),
};
