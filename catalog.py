#!/usr/bin/env python3
"""Каталог скачанного: собирает output/index.csv по файлам в output/.

Что делает:
  * проходит по output/ и находит медиафайлы (mp3, m4a, opus, wav, webm, mp4, mkv)
  * для каждого пишет: дата, имя, тип, размер, есть ли .txt-транскрипт
  * URL восстанавливает из download.log по строкам, которые пишет main.py:
        Скачиваем: <url>
        Готово: <путь> (N MB)      — видео
        Конвертировано: <путь>     — mp3/mp4
        Транскрипция: <путь>       — .txt
    Связка url -> файл точная: берётся ближайшая строка «Скачиваем:» перед
    терминальным событием. Если прогон оборвался и терминального события нет,
    а незакрытый URL ровно один и файлов без URL тоже ровно один — пара
    восстанавливается по порядку и помечается «предположительно».
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

RE_URL = re.compile(r"Скачиваем:\s*(\S+)")
RE_EVENT = re.compile(r"(Готово|Конвертировано|Транскрипция):\s*(.+?)\s*$")
RE_BARE_DONE = re.compile(r"Готово!\s*$")
RE_SIZE = re.compile(r"\s+\([\d.,]+\s*[KMG]B\)\s*$")


def parse_log(log_path: Path) -> tuple[dict[str, tuple[str, str]], set[str], list[str]]:
    """Разбирает download.log.

    Возвращает (url_by_file, transcript_names, pending_urls):
      url_by_file      имя файла -> (url, достоверность)
      transcript_names basenames .txt, для которых была строка «Транскрипция:»
      pending_urls     URL, для которых терминального события не нашлось
    """
    url_by_file: dict[str, tuple[str, str]] = {}
    transcripts: set[str] = set()
    pending: list[str] = []
    if not log_path.exists():
        return url_by_file, transcripts, pending

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return url_by_file, transcripts, pending

    current_url: str | None = None
    closed_urls: set[str] = set()
    for line in text.splitlines():
        m_url = RE_URL.search(line)
        if m_url:
            current_url = m_url.group(1)
            pending.append(current_url)
            continue

        if not current_url:
            continue

        # «Готово!» без пути: прогон завершился, но имя файла в лог не попало —
        # URL считаем закрытым, чтобы он не приклеился к чужому файлу
        if RE_BARE_DONE.search(line):
            closed_urls.add(current_url)
            current_url = None
            continue

        m_ev = RE_EVENT.search(line)
        if not m_ev:
            continue

        kind, raw_path = m_ev.group(1), RE_SIZE.sub("", m_ev.group(2)).strip()
        name = os.path.basename(raw_path)
        if not name:
            continue

        if kind == "Транскрипция":
            transcripts.add(name)
            continue

        url_by_file.setdefault(name, (current_url, "точно"))

    closed = {url for url, _ in url_by_file.values()} | closed_urls
    pending = [u for u in pending if u not in closed]
    return url_by_file, transcripts, pending


def build_index(out_dir: Path, log_path: Path, csv_path: Path) -> list[dict]:
    files = [p for p in out_dir.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXT]
    url_by_file, transcripts, pending = parse_log(log_path)

    unmapped = [p for p in files if p.name not in url_by_file]
    heuristic_url = pending[0] if (len(pending) == 1 and len(unmapped) == 1) else ""

    rows = []
    for p in sorted(files):
        stems_txt = [p.with_suffix(e) for e in TXT_EXT]
        transcript = next((t.name for t in stems_txt if t.exists()), "")

        if p.name in url_by_file:
            url, source = url_by_file[p.name]
        elif heuristic_url:
            url, source = heuristic_url, "предположительно"
        else:
            url, source = "", ""

        st = p.stat()
        rows.append({
            "дата": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "файл": p.name,
            "тип": p.suffix.lower().lstrip("."),
            "размер_МБ": f"{st.st_size / 1024 / 1024:.1f}",
            "транскрипт": transcript or "нет",
            "url": url,
            "url_источник": source,
        })

    rows.sort(key=lambda r: r["дата"], reverse=True)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "дата", "файл", "тип", "размер_МБ", "транскрипт", "url", "url_источник",
        ])
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
    guessed = sum(1 for r in rows if r["url_источник"] == "предположительно")
    total = sum(float(r["размер_МБ"]) for r in rows)
    tail = f" (из них по порядку: {guessed})" if guessed else ""
    print(f"файлов: {len(rows)} | с транскриптом: {with_txt} | с url: {with_url}{tail} | {total:.1f} МБ")
    print(f"каталог: {a.out}")
    for r in rows[:10]:
        mark = {"точно": "url", "предположительно": "url?"}.get(r["url_источник"], "---")
        print(f"  {r['дата']}  {r['тип']:<5} {r['размер_МБ']:>7} МБ  "
              f"{'txt' if r['транскрипт'] != 'нет' else '---'}  {mark:<4} {r['файл'][:44]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
