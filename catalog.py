#!/usr/bin/env python3
"""Каталог скачанного: собирает summaries/index.csv по файлам в output/.

Что делает:
  * проходит по output/ и находит медиафайлы (mp3, m4a, opus, wav, webm, mp4, mkv)
  * для каждого пишет: номер, дата, имя, тип, размер, есть ли .txt-транскрипт,
    исходный заголовок (title), краткое название и файл выжимки
  * URL и title восстанавливает из download.log по строкам, которые пишет main.py:
        Скачиваем: <url> / Скачиваем аудио: <url>
        Заголовок: <title>
        Готово: <путь> (N MB)      — видео
        Конвертировано: <путь>     — mp3/mp4
        Транскрипция: <путь>       — .txt
    Связка url -> файл точная: берётся ближайшая строка «Скачиваем:» перед
    терминальным событием. Если прогон оборвался и терминального события нет,
    а незакрытый URL ровно один и файлов без URL тоже ровно один — пара
    восстанавливается по порядку и помечается «предположительно».
  * Нумерация: 0001, 0002, … в порядке даты по возрастанию («новые снизу»),
    поэтому номера уже существующих файлов не сдвигаются при новых скачиваниях.
  * Выжимки: файлы вида «0002 - краткое название.md» в каталоге рядом с CSV;
    их наличие и краткое название подхватываются в колонки «краткое_название»
    и «выжимка» (файл, где лежит md). Сам текст выжимки скрипт не пишет.

Запуск:  python3 catalog.py [--dir output] [--log download.log] [--out summaries/index.csv]
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

RE_URL = re.compile(r"Скачиваем(?:\s+аудио)?:\s*(\S+)")
RE_TITLE = re.compile(r"Заголовок:\s*(.+?)\s*$")
RE_EVENT = re.compile(r"(Готово|Конвертировано|Транскрипция):\s*(.+?)\s*$")
RE_BARE_DONE = re.compile(r"Готово!\s*$")
RE_SIZE = re.compile(r"\s+\([\d.,]+\s*[KMG]B\)\s*$")
RE_SUMMARY = re.compile(r"^(\d{4})\s*-\s*(.+)\.md$")

FIELDS = [
    "№", "дата", "файл", "тип", "размер_МБ", "транскрипт",
    "title", "краткое_название", "выжимка", "url", "url_источник",
]


def parse_log(log_path: Path) -> tuple[dict[str, tuple[str, str]], set[str], list[str], dict[str, str]]:
    """Разбирает download.log.

    Возвращает (url_by_file, transcript_names, pending_urls, title_by_url):
      url_by_file      имя файла -> (url, достоверность)
      transcript_names basenames .txt, для которых была строка «Транскрипция:»
      pending_urls     URL, для которых терминального события не нашлось
      title_by_url     URL -> «Заголовок:» из лога
    """
    url_by_file: dict[str, tuple[str, str]] = {}
    transcripts: set[str] = set()
    pending: list[str] = []
    title_by_url: dict[str, str] = {}
    if not log_path.exists():
        return url_by_file, transcripts, pending, title_by_url

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return url_by_file, transcripts, pending, title_by_url

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

        m_title = RE_TITLE.search(line)
        if m_title and current_url not in title_by_url:
            title_by_url[current_url] = m_title.group(1)
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
    return url_by_file, transcripts, pending, title_by_url


def scan_summaries(summary_dir: Path) -> dict[int, tuple[str, str]]:
    """Каталог выжимок: номер -> (краткое название, имя файла)."""
    found: dict[int, tuple[str, str]] = {}
    if not summary_dir.is_dir():
        return found
    for p in sorted(summary_dir.iterdir()):
        if not p.is_file():
            continue
        m = RE_SUMMARY.match(p.name)
        if m:
            found[int(m.group(1))] = (m.group(2), p.name)
    return found


def build_index(
    out_dir: Path,
    log_path: Path,
    csv_path: Path,
    summary_dir: Path | None = None,
) -> list[dict]:
    files = [p for p in out_dir.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXT]
    url_by_file, _, pending, title_by_url = parse_log(log_path)
    summaries = scan_summaries(summary_dir or csv_path.parent)

    unmapped = [p for p in files if p.name not in url_by_file]
    heuristic_url = pending[0] if (len(pending) == 1 and len(unmapped) == 1) else ""

    rows = []
    for p in files:
        stems_txt = [p.with_suffix(e) for e in TXT_EXT]
        transcript = next((t.name for t in stems_txt if t.exists()), "")

        if p.name in url_by_file:
            url, source = url_by_file[p.name]
        elif heuristic_url:
            url, source = heuristic_url, "предположительно"
        else:
            url, source = "", ""

        title = title_by_url.get(url, "") or p.stem

        st = p.stat()
        rows.append({
            "_mtime": st.st_mtime,
            "дата": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "файл": p.name,
            "тип": p.suffix.lower().lstrip("."),
            "размер_МБ": f"{st.st_size / 1024 / 1024:.1f}",
            "транскрипт": transcript or "нет",
            "title": title,
            "url": url,
            "url_источник": source,
        })

    # «Новые снизу»: старые первыми, номера = позиция строки (0001, 0002, …)
    rows.sort(key=lambda r: r["_mtime"])
    for i, r in enumerate(rows, start=1):
        short, md = summaries.get(i, ("", ""))
        r["№"] = f"{i:04d}"
        r["краткое_название"] = short
        r["выжимка"] = md or "нет"

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Каталог скачанных файлов + выжимки")
    ap.add_argument("--dir", default="output", help="каталог с медиафайлами (по умолчанию output)")
    ap.add_argument("--log", default="download.log", help="лог скачиваний")
    ap.add_argument("--out", default="summaries/index.csv", help="куда писать CSV")
    ap.add_argument("--summaries", default=None,
                    help="каталог выжимок (по умолчанию — каталог, где лежит CSV)")
    a = ap.parse_args()

    out_dir = Path(a.dir)
    if not out_dir.is_dir():
        print(f"нет каталога {out_dir}")
        return 1

    csv_path = Path(a.out)
    summary_dir = Path(a.summaries) if a.summaries else csv_path.parent
    rows = build_index(out_dir, Path(a.log), csv_path, summary_dir)

    with_txt = sum(1 for r in rows if r["транскрипт"] != "нет")
    with_url = sum(1 for r in rows if r["url"])
    with_md = sum(1 for r in rows if r["выжимка"] != "нет")
    guessed = sum(1 for r in rows if r["url_источник"] == "предположительно")
    total = sum(float(r["размер_МБ"]) for r in rows)
    tail = f" (из них по порядку: {guessed})" if guessed else ""
    print(f"файлов: {len(rows)} | с транскриптом: {with_txt} | "
          f"с выжимкой: {with_md} | с url: {with_url}{tail} | {total:.1f} МБ")
    print(f"каталог: {csv_path}")
    for r in rows[:10]:
        mark = {"точно": "url", "предположительно": "url?"}.get(r["url_источник"], "---")
        print(f"  {r['№']}  {r['дата']}  {r['тип']:<5} {r['размер_МБ']:>7} МБ  "
              f"{'txt' if r['транскрипт'] != 'нет' else '---'}  "
              f"{'md' if r['выжимка'] != 'нет' else '--'}  {mark:<4} {r['файл'][:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
