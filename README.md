# Скачивание видео с YouTube

Скрипт скачивает видео с YouTube.

## Возможности

- ✅ Скачивание видео с YouTube
- ✅ Скачивание только аудиодорожки
- ✅ Транскрипция аудио через Whisper
- ✅ Поддержка SOCKS5/HTTP прокси
- ✅ Автообнаружение доступных форматов
- ✅ Логирование в файл
- ✅ Параллельное скачивание нескольких видео
- ✅ Поддержка плейлистов
- ✅ Конвертация в MP4/MP3 через FFmpeg
- ✅ Прогресс-бар для конвертации

## Установка

```bash
# 1. Клонируем репозиторий
git clone <repo-url>
cd download-video-from-youtube

# 2. Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# или
.\venv\Scripts\activate  # Windows

# 3. Устанавливаем зависимости
pip install -r requirements.txt
```

## Зависимости

- `yt-dlp` — скачивание видео
- `ffmpeg` — конвертация видео/аудио
- `tqdm` — прогресс-бар
- `openai-whisper` — транскрипция (опционально)

### Установка ffmpeg

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

## Быстрый старт

```bash
# Активация окружения
source venv/bin/activate

# Скачивание видео
python main.py "https://www.youtube.com/watch?v=..." --proxy "socks5://127.0.0.1:10808"
```

## Использование

```
usage: main.py [-h] [--resolution RESOLUTION] [--bitrate BITRATE]
               [--cookies COOKIES] [--proxy PROXY]
               [--output OUTPUT] [--playlist]
               [--config-file CONFIG_FILE]
               [--urls URLS [URLS ...]] [--convert]
               [--batch BATCH] [--audio] [--transcribe]
               [--whisper-model WHISPER_MODEL]
               [--whisper-language WHISPER_LANGUAGE] [--clean]
               [url]

Скачивание видео и аудио с YouTube

positional arguments:
  url                   URL видео на YouTube

options:
  --resolution RESOLUTION
                        Макс. разрешение видео
  --bitrate BITRATE     Битрейт аудио (кбит/с)
  --cookies COOKIES     Файл cookies
  --proxy PROXY         SOCKS5/HTTP прокси
  --output OUTPUT       Директория вывода
  --playlist            Обрабатывать плейлисты
  --config-file CONFIG_FILE
                        Файл конфигурации
  --urls URLS [URLS ...]
                        Несколько URL для массового скачивания
  --convert             Конвертировать видео в MP4 через FFmpeg
  --batch BATCH         JSON-файл с массивом задач
  --audio               Скачивать только аудиодорожку
  --transcribe          Транскрибировать аудио через Whisper
  --whisper-model       Модель Whisper: tiny/base/small/medium/large-v3
                        (по умолчанию из config.json: small)
  --whisper-language    Язык распознавания (по умолчанию ru)
  --clean               Очистить каталог вывода перед скачиванием
                        (раньше очистка выполнялась всегда и стирала прошлые файлы)
```

### Заметки по поведению

- По умолчанию файлы в `output/` **не удаляются** — старые ролики и транскрипты остаются.
- Для TikTok/Instagram нужен `curl_cffi<0.14` в venv (impersonation), иначе yt-dlp падает
  с `Unexpected response from webpage request`. Проверка: `venv/bin/yt-dlp -v <url>`,
  в логе должно быть `Impersonation target: <...>`, а не `None`.
- `catalog.py` сканирует только верхний уровень `output/`; `output/subs/` в индекс не попадает.

### Примеры

```bash
# Скачать видео
python main.py "https://www.youtube.com/watch?v=..."

# Скачать аудио
python main.py "URL" --audio

# С транскрипцией
python main.py "URL" --audio --transcribe

# С прокси
python main.py "URL" --proxy "socks5://127.0.0.1:10808"

# С указанием разрешения
python main.py "URL" --resolution 1080

# Массовое скачивание
python main.py --urls "URL1" "URL2" --output ./videos

# Обработать плейлист
python main.py "URL_ПЛЕЙЛИСТА" --playlist

# Конвертировать видео в MP4 через FFmpeg
python main.py "URL" --convert

# Batch-скачивание из JSON-файла
python main.py --batch tasks.json
```

### Batch-конфиг (tasks.json)

```json
[
    {"url": "https://www.youtube.com/watch?v=...", "resolution": 720},
    {"url": "https://www.youtube.com/watch?v=...", "proxy": "socks5://127.0.0.1:10808"},
    {"url": "https://www.youtube.com/watch?v=...", "audio": true, "transcribe": true}
]
```

## Каталог и выжимки

```
output/                 # медиафайлы и .txt-транскрипты (имена — по title)
download.log            # журнал прогонов, из него каталог берёт url и title
summaries/              # каталог выжимок
  index.csv             # каталог: №, дата, файл, тип, размер, транскрипт, title,
                        # краткое_название, выжимка, url, url_источник
  0001 - краткое название.md
  0002 - Дэвид Айк — мы безграничное осознание.md
```

- `python3 catalog.py` (или `--out summaries/index.csv`) перезаписывает `summaries/index.csv`.
- Нумерация `0001, 0002, …` идёт по дате **по возрастанию** — «новые снизу», поэтому номера
  уже существующих файлов не сдвигаются при новых скачиваниях.
- Имя md-файла = `<номер> - <краткое название>.md`; каталог сам подхватывает краткое название
  и файл выжимки в колонки `краткое_название` и `выжимка`.
- Сам текст выжимки скрипт не генерирует — это ручная/агентская работа; каталог только
  фиксирует, что файл существует.
- `title` — исходный заголовок из лога (`Заголовок:`); у TikTok там простыня хештегов,
  поэтому краткое название задаётся отдельно.

## Настройка cookies

1. Установи расширение **Get cookies.txt LOCALLY** в Chrome
2. Открой инкогнито, залогинься на YouTube
3. Перейди на https://www.youtube.com/robots.txt
4. Нажми иконку расширения → **Export**
5. Сохрани файл как `youtube_cookies.txt`

## Конфигурация

Файл `config.json`:

```json
{
    "default_resolution": 720,
    "default_cookies": "youtube_cookies.txt",
    "output_dir": "./output"
}
```

## Логи

Логи сохраняются в `download.log`.

## Структура проекта

```
download-video-from-youtube/
├── main.py              # Скрипт
├── config.json          # Конфигурация
├── requirements.txt     # Зависимости
├── download.log         # Логи
└── output/              # Директория для видео
```

## Устранение неполадок

### Ошибка: `Connection timed out`

1. Проверьте прокси
2. Обновите cookies
3. Попробуйте перезапустить скрипт

### Ошибка: `No module named 'yt_dlp'`

Установите зависимости:
```bash
pip install -r requirements.txt
```

### Ошибка: `No supported JavaScript runtime`

```bash
pip install yt-dlp-ejs
```

## Публикация на GitHub

```bash
# 1. Инициализация репозитория
mkdir download-video-from-youtube
cd download-video-from-youtube

# 2. Добавить файлы
# Скопируйте файлы проекта в директорию

# 3. Инициализация Git
 git init
 git add .
 git commit -m "Initial commit"

# 4. Подключение к GitHub
# Создайте репозиторий на GitHub, затем:
 git remote add origin https://github.com/ваш-ник/download-video-from-youtube.git
 git branch -M main
 git push -u origin main
```

## Обновление

```bash
git pull origin main
pip install -r requirements.txt
```