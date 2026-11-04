#!/usr/bin/env python3
"""Каталог скачанного: собирает output/index.csv по файлам в output/.

Что делает:
  * проходит по output/ и находит медиафайлы (mp3, m4a, opus, wav, webm, mp4, mkv)
  * для каждого пишет: дата, имя, тип, размер, есть ли .txt-транскрипт
  * URL пытается восстановить из download.log (строки "Скачиваем: <url>"):
    сопоставление по имени файла в последующих строках лога; если не нашлось — пусто
  * CSV перезаписывается целиком (идемпотентно), сортировка по дате (новые сверху)

Запуск:  python3 catalog.py [--dir output] [--log download.log] [--out output/index.csv]
"""
from __future__ import annotations

import argparse
import csv
import os
import re
from datetime import datetime
from pathlib import Path

MEDIA_EXT = {".mp3", ".m4a", ".opus", ".wav", ".webm", ".mp4", ".mkv", ".flac"}
TXT_EXT = {".txt", ".srt", ".vtt"}


def parse_log_urls(log_path: Path, names: list[str]) -> dict[str, str]:
    """Грубое сопоставление файл -> URL по download.log.

    Идём по логу, запоминаем последний встреченный "Скачиваем: <url>" и
    привязываем его к имени файла, если имя (или его начало) встретилось
    в строке позже. Ошибки не фатальны: не нашли — URL останется пустым.
    """
    if not log_path.exists():
        return {}
    url_map: dict[str, str] = {}
    current: str | None = None
    keys = {n: n[:40] for n in names}
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        m = re.search(r"Скачиваем:\s*(\S+)", line)
        if m:
            current = m.group(1)
            continue
        if not current:
            continue
        for name, key in keys.items():
            if name in url_map:
                continue
            if key and key in line:
                url_map[name] = current
    return url_map


def build_index(out_dir: Path, log_path: Path, csv_path: Path) -> list[dict]:
    files = [p for p in out_dir.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXT]
    names = [p.name for p in files]
    url_map = parse_log_urls(log_path, names)

    rows = []
    for p in files:
        stems_txt = [p.with_suffix(e) for e in TXT_EXT]
        transcript = next((t.name for t in stems_txt if t.exists()), "")
        st = p.stat()
        rows.append({
            "дата": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "файл": p.name,
            "тип": p.suffix.lower().lstrip("."),
            "размер_МБ": f"{st.st_size / 1024 / 1024:.1f}",
            "транскрипт": transcript or "нет",
            "url": url_map.get(p.name, ""),
        })
    rows.sort(key=lambda r: r["дата"], reverse=True)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["дата", "файл", "тип", "размер_МБ", "транскрипт", "url"])
        w.writeheader()
        w.writerows(rows)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Каталог скачанных файлов")
    ap.add_argument("--dir", default="output", help="каталог с файлами (по умолчанию output)")
    ap.add_argument("--log", default="download.log", help="лог скачиваний")
    ap.add_argument("--out", default="output/index.csv", help="куда писать CSV")
    a = ap.parse_args()

    out_dir = Path(a.dir)
    if not out_dir.is_dir():
        print(f"нет каталога {out_dir}")
        return 1

    rows = build_index(out_dir, Path(a.log), Path(a.out))
    with_txt = sum(1 for r in rows if r["транскрипт"] != "нет")
    with_url = sum(1 for r in rows if r["url"])
    total = sum(float(r["размер_МБ"]) for r in rows)
    print(f"файлов: {len(rows)} | с транскриптом: {with_txt} | с url: {with_url} | {total:.1f} МБ")
    print(f"каталог: {a.out}")
    for r in rows[:10]:
        print(f"  {r['дата']}  {r['тип']:<5} {r['размер_МБ']:>7} МБ  "
              f"{'txt' if r['транскрипт'] != 'нет' else '---'}  {r['файл'][:48]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
