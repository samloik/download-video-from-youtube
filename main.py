#!/usr/bin/env python3
"""
Скачивание видео и аудио с YouTube.
Поддерживает прокси, cookies, автоматическое определение разрешения.
"""

import argparse
import yt_dlp
import subprocess
import os
import sys
import time
import json
import logging
import re
import concurrent.futures
from pathlib import Path
from tqdm import tqdm


def setup_logging(log_file: str = "download.log"):
    """Настройка логирования."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


def load_config(config_path: str = "config.json") -> dict:
    """Загрузка конфигурации из файла."""
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def load_batch_config(batch_path: str) -> list:
    """Загрузка batch-конфига с задачами."""
    if not os.path.exists(batch_path):
        raise FileNotFoundError(f"Файл не найден: {batch_path}")
    with open(batch_path) as f:
        tasks = json.load(f)
    if not isinstance(tasks, list):
        raise ValueError("Batch-конфиг должен быть массивом объектов")
    return tasks


def download_with_retry(ydl: yt_dlp.YoutubeDL, url: str, max_retries: int = 3) -> dict:
    """Скачивание с retry-логикой для сетевых ошибок."""
    last_error = None
    for attempt in range(max_retries):
        try:
            info = ydl.extract_info(url, download=True)
            return info
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 5 * (attempt + 1)
                print(f"🔄 Попытка {attempt + 1}/{max_retries} неудачна, повтор через {wait}с...")
                time.sleep(wait)
            else:
                raise last_error
    return None


def get_available_formats(ydl: yt_dlp.YoutubeDL, url: str) -> list:
    """Получить доступные форматы видео."""
    try:
        info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        mp4_formats = [f for f in formats if f.get('ext') == 'mp4' and f.get('height')]
        return sorted(mp4_formats, key=lambda x: x.get('height', 0), reverse=True)
    except Exception:
        return []


def get_available_audio_formats(ydl: yt_dlp.YoutubeDL, url: str) -> list:
    """Получить доступные аудиоформаты."""
    try:
        info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        audio_formats = [f for f in formats if f.get('acodec') and f.get('ext') in ('mp3', 'm4a', 'webm', 'ogg')]
        return sorted(audio_formats, key=lambda x: x.get('abr', 0), reverse=True)
    except Exception:
        return []


def download_multiple(urls: list, logger: logging.Logger = None, **kwargs) -> list:
    """Параллельное скачивание нескольких видео."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(download_video, url=url, logger=logger, **kwargs): url
            for url in urls
        }
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            try:
                result = future.result()
                results.append(result)
                logger.info(f"Завершено: {url}")
            except Exception as e:
                logger.error(f"Ошибка для {url}: {e}")
                results.append(None)
    return results


def ensure_output_dir(output_dir: str) -> str:
    """Создать директорию для вывода если её нет."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    return output_dir


def clean_output_dir(output_dir: str, logger: logging.Logger = None) -> None:
    """Очистить директорию вывода — только по явному запросу (--clean).

    По умолчанию НЕ вызывается: раньше она стирала все файлы output/ перед
    каждым скачиванием, вместе с прошлыми транскриптами и каталогом.
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    if os.path.exists(output_dir):
        removed = 0
        for file in os.listdir(output_dir):
            file_path = os.path.join(output_dir, file)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    removed += 1
            except Exception as e:
                logger.error(f"Не удалось удалить {file_path}: {e}")
        logger.info(f"Очищено файлов в {output_dir}: {removed}")


def convert_to_mp4(input_file: str, output_file: str, duration: int, logger: logging.Logger = None) -> bool:
    """Конвертирует видео в MP4 через FFmpeg."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    try:
        cmd = [
            'ffmpeg', '-i', input_file,
            '-c:v', 'libx264',
            '-profile:v', 'baseline',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-y', output_file
        ]
        
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, bufsize=1)
        pbar = tqdm(total=duration, desc="Конвертация", unit="с")
        
        for line in proc.stderr:
            match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d+)', line)
            if match:
                h, m, s = map(float, match.groups())
                current = int(h * 3600 + m * 60 + s)
                pbar.update(current - pbar.n)
        
        proc.wait()
        pbar.close()
        
        if proc.returncode == 0:
            logger.info(f"Конвертировано: {output_file}")
            return True
        else:
            logger.error(f"Ошибка FFmpeg")
            return False
    except FileNotFoundError:
        logger.error("FFmpeg не найден. Установите ffmpeg.")
        return False


def convert_to_mp3(input_file: str, output_file: str, duration: int, logger: logging.Logger = None) -> bool:
    """Конвертирует аудио в MP3 через FFmpeg."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    try:
        cmd = [
            'ffmpeg', '-i', input_file,
            '-vn', '-c:a', 'libmp3lame',
            '-b:a', '128k',
            '-y', output_file
        ]
        
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, bufsize=1)
        pbar = tqdm(total=duration, desc="Конвертация", unit="с")
        
        for line in proc.stderr:
            match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d+)', line)
            if match:
                h, m, s = map(float, match.groups())
                current = int(h * 3600 + m * 60 + s)
                pbar.update(current - pbar.n)
        
        proc.wait()
        pbar.close()
        
        if proc.returncode == 0:
            logger.info(f"Конвертировано: {output_file}")
            return True
        else:
            logger.error(f"Ошибка FFmpeg")
            return False
    except FileNotFoundError:
        logger.error("FFmpeg не найден. Установите ffmpeg.")
        return False


def transcribe_audio(
    audio_file: str,
    model: str = "small",
    language: str = "ru",
    logger: logging.Logger = None
) -> str:
    """Транскрибует аудио через Whisper."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    try:
        import whisper
        logger.info(f"Загружаем модель {model}...")
        model_obj = whisper.load_model(model)
        logger.info("Распознаём речь...")
        result = model_obj.transcribe(audio_file, language=language)
        return result.get("text", "")
    except ImportError:
        logger.error("Whisper не установлен. pip install openai-whisper")
        return ""
    except Exception as e:
        logger.error(f"Ошибка транскрипции: {e}")
        return ""


def download_video(
    url: str,
    resolution: int = None,
    cookies_file: str = None,
    proxy: str = None,
    output_dir: str = None,
    process_playlist: bool = False,
    config: dict = None,
    logger: logging.Logger = None,
    convert: bool = False,
    clean: bool = False
):
    """
    Скачивает видео с YouTube.
    
    Args:
        url: URL видео
        resolution: максимальное разрешение ширины
        cookies_file: путь к файлу cookies
        proxy: SOCKS5/HTTP прокси
        output_dir: директория для сохранения
        process_playlist: обрабатывать плейлисты
        config: конфигурация из файла
        logger: логгер
        convert: конвертировать в MP4 через FFmpeg
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    # Значения по умолчанию из конфига
    if config is None:
        config = {}
    resolution = resolution or config.get('default_resolution', 720)
    cookies_file = cookies_file or config.get('default_cookies', 'youtube_cookies.txt')
    proxy = proxy or config.get('default_proxy')
    output_dir = output_dir or config.get('output_dir', '.')
    
    # Создаём директорию; чистим только по явному --clean
    ensure_output_dir(output_dir)
    if clean:
        clean_output_dir(output_dir, logger=logger)
    logger.info(f"Директория вывода: {output_dir}")
    
    # Автообнаружение форматов
    with yt_dlp.YoutubeDL({'quiet': True, 'proxy': proxy}) as ydl:
        formats = get_available_formats(ydl, url)
        if formats:
            max_height = formats[0].get('height', resolution or 720)
            if max_height < (resolution or 720):
                logger.info(f"Доступное разрешение {max_height}p ниже целевого {resolution}p")
                resolution = max_height
    
    ydl_opts = {
        'format': f'bestvideo[height<={resolution or 720}][ext=mp4]+bestaudio/best',
        'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
        'quiet': False,
        'extractor_retries': 10,
        'http_chunk_size': 10485760,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'sleep_interval': 10,
        'max_sleep_interval': 60,
        'socket_timeout': 120,
        'download_timeout': 300,
        'extract_flat': 'playlist' if process_playlist else False,
        'playlistend': 5 if process_playlist else None,
    }

    # Прокси (опционально)
    if proxy:
        ydl_opts['proxy'] = proxy
        logger.info(f"Прокси: {proxy}")

    # Cookies
    if os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 100:
        ydl_opts['cookiefile'] = cookies_file
        logger.info(f"Cookies: {cookies_file}")
    else:
        logger.warning("Cookies не найдены")

    try:
        logger.info(f"Скачиваем: {url}")
        start_time = time.time()

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = download_with_retry(ydl, url)
            downloaded_file = ydl.prepare_filename(info)

        duration = info.get('duration', 0) or 0
        title = info.get('title', 'video')
        logger.info(f"Заголовок: {title}")
        logger.info(f"Длительность: {duration} сек")
        logger.info(f"Время загрузки: {time.time() - start_time:.1f} с")

        # Конвертация в MP4
        if convert:
            logger.info("Конвертируем в MP4...")
            base_name = os.path.splitext(downloaded_file)[0]
            output_file = base_name + '.mp4'
            if convert_to_mp4(downloaded_file, output_file, duration, logger):
                os.remove(downloaded_file)
                logger.info("Готово!")
                return output_file
            else:
                logger.info("Готово (оригинал сохранён)!")
                return downloaded_file

        logger.info("Готово!")
        return downloaded_file

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Ошибка загрузки: {e}")
        return None
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return None


def download_audio(
    url: str,
    bitrate: int = None,
    cookies_file: str = None,
    proxy: str = None,
    output_dir: str = None,
    config: dict = None,
    logger: logging.Logger = None,
    convert: bool = True,
    transcribe: bool = False,
    whisper_model=None,
    whisper_language=None,
    clean: bool = False
):
    """
    Скачивает аудиодорожку с YouTube.
    
    Args:
        url: URL видео
        bitrate: битрейт аудио (по умолчанию 128)
        cookies_file: путь к файлу cookies
        proxy: SOCKS5/HTTP прокси
        output_dir: директория для сохранения
        config: конфигурация из файла
        logger: логгер
        convert: конвертировать в MP3 через FFmpeg
        transcribe: транскрибировать аудио
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    if config is None:
        config = {}
    bitrate = bitrate or config.get('default_bitrate', 128)
    cookies_file = cookies_file or config.get('default_cookies', 'youtube_cookies.txt')
    proxy = proxy or config.get('default_proxy')
    output_dir = output_dir or config.get('output_dir', '.')
    whisper_model = whisper_model or config.get('whisper_model', 'small')
    whisper_language = whisper_language or config.get('whisper_language', 'ru')
    
    ensure_output_dir(output_dir)
    if clean:
        clean_output_dir(output_dir, logger=logger)
    logger.info(f"Директория вывода: {output_dir}")
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
        'quiet': False,
        'extractor_retries': 10,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'sleep_interval': 10,
        'max_sleep_interval': 60,
        'socket_timeout': 120,
        'download_timeout': 300,
    }

    if proxy:
        ydl_opts['proxy'] = proxy
        logger.info(f"Прокси: {proxy}")

    if os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 100:
        ydl_opts['cookiefile'] = cookies_file
        logger.info(f"Cookies: {cookies_file}")
    else:
        logger.warning("Cookies не найдены")

    try:
        logger.info(f"Скачиваем аудио: {url}")
        start_time = time.time()

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = download_with_retry(ydl, url)
            downloaded_file = ydl.prepare_filename(info)

        duration = info.get('duration', 0) or 0
        title = info.get('title', 'audio')
        logger.info(f"Заголовок: {title}")
        logger.info(f"Длительность: {duration} сек")
        logger.info(f"Время загрузки: {time.time() - start_time:.1f} с")

        # Конвертация в MP3
        if convert:
            logger.info("Конвертируем в MP3...")
            base_name = os.path.splitext(downloaded_file)[0]
            output_file = base_name + '.mp3'
            if convert_to_mp3(downloaded_file, output_file, duration, logger):
                os.remove(downloaded_file)
                logger.info("Готово!")
                
                # Транскрибация
                if transcribe:
                    logger.info(f"Транскрибируем (модель {whisper_model}, язык {whisper_language})...")
                    text = transcribe_audio(
                        output_file,
                        model=whisper_model,
                        language=whisper_language,
                        logger=logger
                    )
                    if text:
                        txt_file = base_name + '.txt'
                        with open(txt_file, 'w', encoding='utf-8') as f:
                            f.write(text)
                        logger.info(f"Транскрипция: {txt_file}")
                
                return output_file
            else:
                logger.info("Готово (оригинал сохранён)!")
                return downloaded_file

        logger.info("Готово!")
        return downloaded_file

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Ошибка загрузки: {e}")
        return None
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return None


if __name__ == "__main__":
    config = load_config()
    logger = setup_logging()
    
    parser = argparse.ArgumentParser(description="Скачивание видео и аудио с YouTube")
    parser.add_argument("url", nargs="?", help="URL видео на YouTube")
    parser.add_argument("--resolution", type=int, help="Макс. разрешение видео")
    parser.add_argument("--bitrate", type=int, help="Битрейт аудио (кбит/с)")
    parser.add_argument("--cookies", help="Файл cookies")
    parser.add_argument("--proxy", help="SOCKS5/HTTP прокси")
    parser.add_argument("--output", help="Директория вывода")
    parser.add_argument("--playlist", action="store_true", help="Обрабатывать плейлисты")
    parser.add_argument("--config-file", default="config.json", help="Файл конфигурации")
    parser.add_argument("--urls", nargs="+", help="Несколько URL для массового скачивания")
    parser.add_argument("--convert", action="store_true", help="Конвертировать видео в MP4 через FFmpeg")
    parser.add_argument("--batch", help="JSON-файл с массивом задач для массового скачивания")
    parser.add_argument("--audio", action="store_true", help="Скачивать только аудиодорожку")
    parser.add_argument("--transcribe", action="store_true", help="Транскрибировать аудио через Whisper")
    parser.add_argument("--whisper-model", default=None,
                        help="Модель Whisper: tiny/base/small/medium/large-v3 (по умолчанию из config.json или small)")
    parser.add_argument("--whisper-language", default=None,
                        help="Язык распознавания (по умолчанию из config.json или ru)")
    parser.add_argument("--clean", action="store_true",
                        help="Очистить каталог вывода перед скачиванием (раньше делалось всегда)")
    
    args = parser.parse_args()
    
    # Поддержка batch-конфига
    if args.batch:
        tasks = load_batch_config(args.batch)
        results = []
        for task in tasks:
            # transcribe/convert/whisper_* вынимаем из task, чтобы не дублировать
            # именованные аргументы (раньше это давало TypeError)
            task_config = {
                k: v for k, v in task.items()
                if k not in ('url', 'audio', 'transcribe', 'convert')
            }
            task_transcribe = bool(task.get('transcribe', args.transcribe))
            task_convert = bool(task.get('convert', args.convert))
            if task.get('audio'):
                result = download_audio(
                    url=task.get('url'),
                    logger=logger,
                    config=config,
                    transcribe=task_transcribe,
                    whisper_model=args.whisper_model,
                    whisper_language=args.whisper_language,
                    clean=args.clean,
                    **task_config
                )
            else:
                result = download_video(
                    url=task.get('url'),
                    logger=logger,
                    config=config,
                    convert=task_convert,
                    clean=args.clean,
                    **task_config
                )
            results.append(result)
        sys.exit(0 if all(results) else 1)
    
    # Поддержка массового скачивания
    urls = args.urls or ([args.url] if args.url else [])
    
    if not urls:
        parser.error("Укажите URL видео, --urls или --batch")
    
    if len(urls) > 1:
        results = download_multiple(
            urls, logger=logger,
            resolution=args.resolution,
            cookies_file=args.cookies,
            proxy=args.proxy,
            output_dir=args.output,
            process_playlist=args.playlist,
            config=config,
            convert=args.convert,
            clean=args.clean
        )
    else:
        if args.audio:
            result = download_audio(
                url=urls[0],
                bitrate=args.bitrate,
                cookies_file=args.cookies,
                proxy=args.proxy,
                output_dir=args.output,
                config=config,
                logger=logger,
                convert=True,
                transcribe=args.transcribe,
                whisper_model=args.whisper_model,
                whisper_language=args.whisper_language,
                clean=args.clean
            )
        else:
            result = download_video(
                url=urls[0],
                resolution=args.resolution,
                cookies_file=args.cookies,
                proxy=args.proxy,
                output_dir=args.output,
                process_playlist=args.playlist,
                config=config,
                logger=logger,
                convert=args.convert,
                clean=args.clean
            )
    
    sys.exit(0 if result else 1)