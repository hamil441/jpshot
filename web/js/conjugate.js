// Conjugation tables from the dictionary form and the IPADIC conjugation type.
const GODAN = { "う": "わいえお", "く": "かきけこ", "ぐ": "がぎげご", "す": "さしせそ", "つ": "たちてと",
  "ぬ": "なにねの", "ぶ": "ばびべぼ", "む": "まみめも", "る": "らりれろ" };
const TE = { "う": "って", "つ": "って", "る": "って", "む": "んで", "ぶ": "んで", "ぬ": "んで", "く": "いて", "ぐ": "いで", "す": "して" };
const past = (te) => te.slice(0, -1) + (te.endsWith("で") ? "だ" : "た");

export function conjugations(tok) {
  const base = tok.base, ct = tok.ctype || "";
  if (!base) return [];
  if (tok.pos === "形容詞") {
    const stem = base === "いい" ? "よ" : base.slice(0, -1);
    return [["polite", base + "です"], ["negative", stem + "くない"], ["past", stem + "かった"],
      ["past negative", stem + "くなかった"], ["te-form", stem + "くて"], ["adverb", stem + "く"], ["if", stem + "ければ"]];
  }
  if (tok.pos === "名詞" && tok.pos1 === "形容動詞語幹") {
    return [["before a noun", base + "な"], ["is", base + "だ"], ["polite", base + "です"], ["negative", base + "じゃない"],
      ["past", base + "だった"], ["te-form", base + "で"], ["adverb", base + "に"]];
  }
  if (tok.pos !== "動詞") return [];
  if (ct.startsWith("サ変")) {
    const pre = base.endsWith("する") ? base.slice(0, -2) : base.endsWith("ずる") ? base.slice(0, -2) : "";
    return [["polite", "します"], ["negative", "しない"], ["past", "した"], ["past negative", "しなかった"], ["te-form", "して"],
      ["potential", "できる"], ["passive", "される"], ["causative", "させる"], ["volitional", "しよう"], ["if", "すれば"],
      ["command", "しろ"]].map(([l, f]) => [l, pre + f]);
  }
  if (ct.startsWith("カ変")) {
    const k = base.startsWith("来");
    const r = (kanji, kana) => (k ? "来" + kanji : kana);
    return [["polite", r("ます", "きます")], ["negative", r("ない", "こない")], ["past", r("た", "きた")],
      ["past negative", r("なかった", "こなかった")], ["te-form", r("て", "きて")], ["potential", r("られる", "こられる")],
      ["volitional", r("よう", "こよう")], ["if", r("れば", "くれば")], ["command", r("い", "こい")]];
  }
  if (ct.startsWith("一段")) {
    const s = base.slice(0, -1);
    return [["polite", s + "ます"], ["negative", s + "ない"], ["past", s + "た"], ["past negative", s + "なかった"],
      ["te-form", s + "て"], ["potential", s + "られる"], ["passive", s + "られる"], ["causative", s + "させる"],
      ["volitional", s + "よう"], ["if", s + "れば"], ["command", s + "ろ"]];
  }
  const end = base.slice(-1);
  if (!ct.startsWith("五段") || !GODAN[end]) return [];
  const s = base.slice(0, -1), [a, i, e, o] = GODAN[end];
  let te = s + TE[end];
  if (base === "行く" || base === "いく") te = s + "って";
  const neg = base === "ある" ? "ない" : s + a + "ない";
  return [["polite", s + i + "ます"], ["negative", neg], ["past", past(te)], ["past negative", neg.slice(0, -1) + "かった"],
    ["te-form", te], ["potential", s + e + "る"], ["passive", s + a + "れる"], ["causative", s + a + "せる"],
    ["volitional", s + o + "う"], ["if", s + e + "ば"], ["command", s + e]];
}

export function tableHTML(rows) {
  if (!rows.length) return "";
  return `<div class="forms"><b>Forms:</b> ` + rows.map(([l, f]) => `<span class="muted">${l}</span> ${f}`).join(" · ") + "</div>";
}
