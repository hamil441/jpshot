// On-device OCR with Tesseract.js (Japanese + English), with screenshot-friendly preprocessing.
const TESS = "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js";
let workerP = null;

function loadScript(src) {
  return new Promise((res, rej) => {
    if (window.Tesseract) return res();
    const s = document.createElement("script");
    s.src = src; s.onload = res; s.onerror = () => rej(new Error("couldn't load the OCR engine (offline?)"));
    document.head.appendChild(s);
  });
}

export function getWorker(onProgress) {
  if (!workerP) {
    workerP = (async () => {
      await loadScript(TESS);
      const w = await window.Tesseract.createWorker(["jpn", "eng"], 1, {
        logger: (m) => onProgress && onProgress(m),
      });
      await w.setParameters({ tessedit_pageseg_mode: "6", preserve_interword_spaces: "1" });
      return w;
    })();
    workerP.catch(() => { workerP = null; });
  }
  return workerP;
}

/** Grayscale, invert dark backgrounds, upscale small crops. Returns a canvas. */
export function prepare(img, crop) {
  const { x, y, w, h } = crop || { x: 0, y: 0, w: img.naturalWidth || img.width, h: img.naturalHeight || img.height };
  const scale = h < 120 ? 3 : Math.max(w, h) < 1600 ? 2 : 1;
  const c = document.createElement("canvas");
  c.width = Math.round(w * scale) + 40; c.height = Math.round(h * scale) + 40;
  const g = c.getContext("2d", { willReadFrequently: true });
  g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
  g.imageSmoothingQuality = "high";
  g.drawImage(img, x, y, w, h, 20, 20, w * scale, h * scale);
  const d = g.getImageData(0, 0, c.width, c.height), px = d.data;
  let sum = 0;
  for (let i = 0; i < px.length; i += 4) { const v = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]; px[i] = px[i + 1] = px[i + 2] = v; sum += v; }
  if (sum / (px.length / 4) < 110) for (let i = 0; i < px.length; i += 4) px[i] = px[i + 1] = px[i + 2] = 255 - px[i];
  g.putImageData(d, 0, 0);
  return c;
}

const JA = /[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ々〆〇]/;
const JA_OR_PUNCT = /[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ々〆〇、。「」『』（）！？・…〜：；，．]/;

export async function recognize(canvas, minConf = 55, onProgress) {
  const w = await getWorker(onProgress);
  const { data } = await w.recognize(canvas);
  const lines = [];
  let confs = [];
  for (const line of data.lines || []) {
    let out = "";
    for (const word of line.words || []) {
      const t = (word.text || "").trim();
      if (!t || word.confidence < minConf) continue;
      confs.push(word.confidence);
      if (out && !(JA_OR_PUNCT.test(out.slice(-1)) && JA_OR_PUNCT.test(t[0]))) out += " ";
      out += t;
    }
    if (out.trim()) lines.push(out.trim());
  }
  const text = lines.join("\n");
  const ja = [...text].filter((c) => JA.test(c)).length, la = (text.match(/[A-Za-z]/g) || []).length;
  if (ja + la < 2) return null;
  const language = ja / (ja + la) >= 0.3 ? "ja" : "en";
  const fixed = language === "en" ? text.replace(/(^|\s)\|(?=\s)/g, "$1I") : text;
  if (language === "en" && !/[A-Za-z]{2,}/.test(fixed)) return null;
  return { text: fixed, language, confidence: confs.reduce((a, b) => a + b, 0) / Math.max(1, confs.length) };
}
