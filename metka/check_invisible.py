#!/usr/bin/env python3
"""Ищет в тексте «невидимые» символы, которые часто путают с водяным знаком.

Проверяет:
  * нулевой ширины и управляющие: U+200B..U+200F, U+2060..U+2064, U+FEFF, U+00AD (мягкий перенос),
    U+034F, U+180E, двунаправленные U+202A..U+202E, U+2066..U+2069;
  * теговые символы U+E0000..U+E007F и селекторы вариантов U+FE00..U+FE0F, U+E0100..U+E01EF;
  * нестандартные пробелы: U+00A0, U+2000..U+200A, U+202F, U+205F, U+3000;
  * нестандартные дефисы: U+2010, U+2011 (неразрывный), U+2012, U+2043, U+FE63, U+FF0D;
  * прочие символы категорий Cf/Co/Cn и управляющие Cc, кроме \\n \\r \\t;
  * гомоглифы: латинские буквы внутри русского слова и наоборот.

Это НЕ детектор статистического водяного знака Claude/OpenAI: тот живёт в выборе слов,
а не в символах, и без секретного ключа вендора его не увидеть.

Использование:
  python3 check_invisible.py файл1.txt [файл2.txt ...]   # отчёт по каждому
  pbpaste | python3 check_invisible.py -                  # из буфера обмена (macOS)
  python3 check_invisible.py --json ...                   # машинный вывод
Код выхода: 0 — ничего не найдено, 1 — найдено.
Склейка эмодзи (U+200D между эмодзи, как в 👩‍🎨) и U+FE0F после эмодзи — норма, их показываем, но не считаем.
"""
import json
import re
import sys
import unicodedata

ZERO_WIDTH = set(range(0x200B, 0x2010)) | set(range(0x2060, 0x2065)) | {0xFEFF, 0x00AD, 0x034F, 0x180E}
BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
TAGS = set(range(0xE0000, 0xE0080))
VARSEL = set(range(0xFE00, 0xFE10)) | set(range(0xE0100, 0xE01F0))
ODD_SPACES = {0x00A0, 0x202F, 0x205F, 0x3000} | set(range(0x2000, 0x200B))
ODD_HYPHENS = {0x2010, 0x2011, 0x2012, 0x2043, 0xFE63, 0xFF0D}

CYR = re.compile(r"[Ѐ-ӿ]")
LAT = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[\w­​-‏⁠-⁤﻿]+", re.U)


def classify(cp):
    if cp in ZERO_WIDTH:
        return "нулевой ширины"
    if cp in BIDI:
        return "управление направлением"
    if cp in TAGS:
        return "теговый символ"
    if cp in VARSEL:
        return "селектор варианта"
    if cp in ODD_SPACES:
        return "нестандартный пробел"
    if cp in ODD_HYPHENS:
        return "нестандартный дефис"
    ch = chr(cp)
    cat = unicodedata.category(ch)
    if cat in ("Cf", "Co", "Cn"):
        return f"служебный ({cat})"
    if cat == "Cc" and ch not in "\n\r\t":
        return "управляющий (Cc)"
    return None


def scan(text):
    hits = []
    for i, ch in enumerate(text):
        cp = ord(ch)
        prev_emoji = i > 0 and unicodedata.category(text[i - 1]) == "So"
        next_emoji = i + 1 < len(text) and unicodedata.category(text[i + 1]) == "So"
        if cp == 0xFE0F and prev_emoji:
            kind = "селектор варианта (после эмодзи, норма)"
        elif cp == 0x200D and prev_emoji and next_emoji:
            kind = "склейка эмодзи (норма)"
        else:
            kind = classify(cp)
        if kind:
            hits.append({
                "pos": i,
                "code": f"U+{cp:04X}",
                "name": unicodedata.name(ch, "?"),
                "kind": kind,
                "context": text[max(0, i - 15):i + 15].replace("\n", "⏎"),
            })
    mixed = []
    for m in WORD.finditer(text):
        w = m.group(0)
        if CYR.search(w) and LAT.search(w):
            mixed.append({"pos": m.start(), "word": w})
    return hits, mixed


def main(argv):
    as_json = "--json" in argv
    paths = [a for a in argv if a != "--json"] or ["-"]
    total = {"files": 0, "chars": 0, "hits": 0, "suspicious_hits": 0, "mixed_words": 0}
    report = []
    for p in paths:
        text = sys.stdin.read() if p == "-" else open(p, encoding="utf-8", newline="").read()
        hits, mixed = scan(text)
        susp = [h for h in hits if "норма" not in h["kind"]]
        total["files"] += 1
        total["chars"] += len(text)
        total["hits"] += len(hits)
        total["suspicious_hits"] += len(susp)
        total["mixed_words"] += len(mixed)
        report.append({"file": p, "chars": len(text), "hits": hits, "mixed_words": mixed})
        if not as_json:
            status = "ЧИСТО" if not susp and not mixed else "НАЙДЕНО"
            print(f"{p}: {len(text)} симв. — {status}")
            for h in hits:
                print(f"   {h['code']} {h['name']} [{h['kind']}] …{h['context']}…")
            for w in mixed:
                print(f"   смешанное слово (гомоглиф?): {w['word']!r}")
    if as_json:
        print(json.dumps({"total": total, "files": report}, ensure_ascii=False, indent=1))
    else:
        print(f"\nИтого: файлов {total['files']}, символов {total['chars']}, "
              f"подозрительных символов {total['suspicious_hits']}, смешанных слов {total['mixed_words']}")
    return 1 if total["suspicious_hits"] or total["mixed_words"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
