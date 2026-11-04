#!/usr/bin/env python3
"""VTT (авто-субтитры YouTube) -> чистый текст.

Авто-субтитры содержат таймкоды, служебные строки и «катящиеся» повторы
(одна и та же фраза приходит несколько раз по мере появления слов).
Скрипт убирает всё это и склеивает текст в абзацы.

Использование: python3 vtt_to_txt.py <файл.vtt> [<файл2.vtt> ...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RE_CUE_TIME = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->")
RE_TAG = re.compile(r"<[^>]+>")


def vtt_to_text(vtt: Path) -> str:
    lines_out: list[str] = []
    for raw in vtt.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION")):
            continue
        if RE_CUE_TIME.match(line) or line.isdigit():
            continue
        line = RE_TAG.sub("", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        # авто-субтитры повторяют строку, пока идёт фраза: убираем повторы
        if lines_out and (line == lines_out[-1] or lines_out[-1].endswith(line)):
            continue
        if lines_out and line.endswith(lines_out[-1]):
            lines_out[-1] = line
            continue
        lines_out.append(line)

    text = " ".join(lines_out)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    for arg in sys.argv[1:]:
        src = Path(arg)
        if not src.exists():
            print(f"нет файла: {src}")
            continue
        text = vtt_to_text(src)
        dst = src.with_suffix(".txt")
        dst.write_text(text, encoding="utf-8")
        words = len(text.split())
        print(f"{dst.name}: {words} слов, {len(text)} символов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
