#!/usr/bin/env python3
"""Build the compact data files the phone app loads (run by the GitHub Pages workflow).

usage: build_web_data.py SRC_DIR WEB_DIR

SRC_DIR may contain (any missing source is skipped):
  jmdict.json     jmdict-simplified "jmdict-eng-common" (CC BY-SA, EDRDG)
  kanjidic.json   jmdict-simplified "kanjidic2-en"      (CC BY-SA, EDRDG)
  accents.txt     Kanjium pitch accents "word<TAB>reading<TAB>accent[,accent]" (CC BY-SA)

Writes WEB_DIR/data/{dict,kanji,accents}.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAX_SENSES, MAX_GLOSSES = 5, 4


def build_dict(src: Path) -> dict:
    data = json.loads(src.read_text(encoding="utf-8"))
    used_tags: set[str] = set()
    entries = []
    for w in data.get("words", []):
        kanji = [k["text"] for k in w.get("kanji", [])]
        kana = [k["text"] for k in w.get("kana", [])]
        common = any(k.get("common") for k in w.get("kanji", []) + w.get("kana", []))
        senses = []
        for s in w.get("sense", [])[:MAX_SENSES]:
            glosses = [g["text"] for g in s.get("gloss", []) if g.get("lang", "eng") == "eng"][:MAX_GLOSSES]
            if not glosses:
                continue
            pos = s.get("partOfSpeech", [])
            used_tags.update(pos)
            senses.append([pos, glosses])
        if senses and (kanji or kana):
            entries.append([kanji, kana, senses, 1 if common else 0])
    tags = {t: d for t, d in data.get("tags", {}).items() if t in used_tags}
    print(f"dict: {len(entries)} entries, {len(tags)} tags")
    return {"e": entries, "t": tags}


def build_kanji(src: Path) -> dict:
    data = json.loads(src.read_text(encoding="utf-8"))
    out = {}
    for c in data.get("characters", []):
        lit = c.get("literal")
        misc = c.get("misc", {})
        grade, jlpt, freq = misc.get("grade"), misc.get("jlptLevel"), misc.get("frequency")
        if not (grade or jlpt or (freq and freq <= 2500)):
            continue   # keep the kanji learners actually meet
        meanings, on, kun = [], [], []
        for g in c.get("readingMeaning", {}).get("groups", []) if c.get("readingMeaning") else []:
            meanings += [m["value"] for m in g.get("meanings", []) if m.get("lang", "en") == "en"]
            on += [r["value"] for r in g.get("readings", []) if r.get("type") == "ja_on"]
            kun += [r["value"] for r in g.get("readings", []) if r.get("type") == "ja_kun"]
        strokes = (misc.get("strokeCounts") or [None])[0]
        # old JLPT (4 = easiest) -> approximate N level (5 = easiest)
        n = {4: 5, 3: 4, 2: 3, 1: 1}.get(jlpt) if jlpt else None
        out[lit] = [meanings[:5], on[:3], kun[:4], strokes, grade, n, freq]
    print(f"kanji: {len(out)} characters")
    return out


def build_accents(src: Path) -> dict:
    out: dict[str, list] = {}
    for line in src.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0] or not parts[2]:
            continue
        word, reading, acc = parts[0], parts[1] or parts[0], parts[2]
        accs = [int(a) for a in acc.replace(" ", "").split(",") if a.isdigit()]
        if accs:
            out.setdefault(word, []).append([reading, accs])
    print(f"accents: {len(out)} words")
    return out


def main(src_dir: str, web_dir: str) -> None:
    src, dest = Path(src_dir), Path(web_dir) / "data"
    dest.mkdir(parents=True, exist_ok=True)
    jobs = [("jmdict.json", "dict.json", build_dict), ("kanjidic.json", "kanji.json", build_kanji),
            ("accents.txt", "accents.json", build_accents)]
    for name, out_name, fn in jobs:
        path = src / name
        if not path.exists():
            print(f"skip {name}: not found")
            continue
        result = fn(path)
        (dest / out_name).write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                                     encoding="utf-8")
        print(f"wrote {out_name}: {(dest / out_name).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
