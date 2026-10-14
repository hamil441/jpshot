// Online helpers: translation, speech, the explanation writer (Anthropic API) and settings/storage.

// -- settings ------------------------------------------------------------------------------
const DEFAULTS = {
  features: [], sections: ["furigana", "english"], colorMode: "none", theme: "system", speed: 1.0, voice: "",
  apiKey: "", model: "claude-haiku-5-5", jaSize: 24, furiganaUnknownOnly: false,
  ankiUrl: "http://127.0.0.1:8765", ankiDeck: "", ankiReading: true, ankiHearing: false, ankiRandomFont: true,
  ankiTags: "jpshot", ankiMobileProfile: "", ankiMobileDeck: "JPShot", ankiMobileType: "JPShot Sentence",
  knownQuery: "", knownFields: "Word, Vocabulary-Kanji, Expression, Vocab, VocabKanji, Kanji, Front",
  showImage: true,
};
export const settings = (() => {
  let s = {};
  try { s = JSON.parse(localStorage.getItem("jpshot.settings") || "{}"); } catch (_) { /* private mode */ }
  return { ...DEFAULTS, ...s };
})();
export function saveSettings() {
  try { localStorage.setItem("jpshot.settings", JSON.stringify(settings)); } catch (_) { /* ignore */ }
}
export const feat = (k) => settings.features.includes(k);

export function local(key, fallback) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (_) { return fallback; }
}
export function setLocal(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* full or blocked */ }
}

// -- translation ----------------------------------------------------------------------------
export async function translate(text, src, dst) {
  if (!text.trim()) return "";
  const errors = [];
  try {
    const u = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=${src}&tl=${dst}&dt=t&q=${encodeURIComponent(text)}`;
    const r = await fetch(u);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    const out = (d[0] || []).map((s) => s && s[0]).filter(Boolean).join("");
    if (out.trim()) return out;
  } catch (e) { errors.push(`google: ${e.message}`); }
  try {
    const r = await fetch(`https://api.mymemory.translated.net/get?q=${encodeURIComponent(text.slice(0, 480))}&langpair=${src}|${dst}`);
    const d = await r.json();
    if (Number(d.responseStatus) === 200) return d.responseData.translatedText;
    errors.push(`mymemory: ${d.responseDetails}`);
  } catch (e) { errors.push(`mymemory: ${e.message}`); }
  throw new Error("translation failed (" + errors.join("; ") + ")");
}

// -- speech --------------------------------------------------------------------------------------
export function jaVoices() {
  return (window.speechSynthesis?.getVoices() || []).filter((v) => /^ja/i.test(v.lang));
}
let currentUtterance = null;
export function speak(text, rate = 1, voiceName = "", onEnd = null) {
  stopSpeaking();
  const voices = jaVoices();
  if (!window.speechSynthesis || !voices.length) {
    // no Japanese system voice: fall back to Google's voice in an <audio> element
    const a = new Audio(googleTTS(text));
    a.playbackRate = rate;
    a.onended = () => onEnd && onEnd();
    a.play().catch(() => onEnd && onEnd());
    currentUtterance = a;
    return;
  }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "ja-JP";
  u.rate = rate;
  u.voice = voices.find((v) => v.name === voiceName) || voices[0];
  u.onend = () => onEnd && onEnd();
  u.onerror = () => onEnd && onEnd();
  currentUtterance = u;
  window.speechSynthesis.speak(u);
}
export function stopSpeaking() {
  if (currentUtterance instanceof Audio) currentUtterance.pause();
  window.speechSynthesis?.cancel();
  currentUtterance = null;
}
export const googleTTS = (text) =>
  `https://translate.google.com/translate_tts?ie=UTF-8&tl=ja&client=tw-ob&q=${encodeURIComponent(text.slice(0, 200))}`;

// -- explanation writer (Anthropic API from the browser) ----------------------------------------
export const hasWriter = () => !!settings.apiKey;
export async function chat(messages, system = "", maxTokens = 900) {
  if (!settings.apiKey) throw new Error("No API key — add one in Settings → Explanations");
  const body = { model: settings.model || "claude-haiku-5-5", max_tokens: maxTokens, messages };
  if (system) body.system = system;
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": settings.apiKey, "anthropic-version": "2023-06-01", "content-type": "application/json",
      "anthropic-dangerous-direct-browser-access": "true" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error?.message || `HTTP ${r.status}`);
  return (d.content || []).filter((b) => b.type === "text").map((b) => b.text).join("");
}

const sentences = (t) => t.trim().split(/(?<=[.!?])\s+/).filter(Boolean);
export async function shortExplanation(cacheKey, prompt, maxSentences) {
  const stories = local("jpshot.stories", {});
  const key = `${cacheKey}|${settings.model}`;
  if (stories[key]) return stories[key];
  const raw = await chat([{ role: "user", content: prompt }], "", 160);
  const text = sentences(raw.replace(/[*_#`]+/g, "").replace(/\s+/g, " ").replace(/^"|"$/g, "")).slice(0, maxSentences).join(" ");
  if (text) { stories[key] = text; setLocal("jpshot.stories", stories); }
  return text;
}
