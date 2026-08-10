# VK Video Downloader

Кросс-платформенный контент-менеджер для скачивания видео VK / VK Video.

- Локальный веб-интерфейс (Windows 11: окно WebView2)
- Все зависимости в portable-сборке (Python runtime, yt-dlp, ffmpeg)
- Прогресс-бар и ETA при скачивании
- Проверка и установка обновлений из GitHub Releases

Репозиторий: https://github.com/nix2open/vk-video-downloader

## Для пользователей (Windows 11)

1. Скачайте `VKVideoDownloader-windows-x64.zip` из [Releases](https://github.com/nix2open/vk-video-downloader/releases)
2. Распакуйте в любую папку
3. Запустите `VKVideoDownloader.exe`
4. В интерфейсе: вставить ссылку → Анализ → качество → Скачать
5. Кнопка **Проверить обновления** скачает и установит новую версию после публикации релиза

Ничего дополнительно ставить не нужно (WebView2 уже есть в Windows 11).

## Для разработки

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python launcher.py
```

Откроется http://127.0.0.1:8787

## Как публиковать обновление

1. Внесите изменения в код
2. Обновите `VERSION` (например `1.0.1`)
3. Закоммитьте и создайте тег:

```bash
git add -A && git commit -m "release: 1.0.1"
git tag v1.0.1
git push origin main --tags
```

4. GitHub Actions соберёт Windows zip и приложит к Release
5. Клиенты нажмут «Проверить обновления» → «Скачать и установить»

## API

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Статус |
| GET | `/api/version` | Версия клиента |
| POST | `/api/analyze` | Анализ ссылки |
| POST | `/api/download` | Старт скачивания (job) |
| GET | `/api/jobs/{id}/events` | SSE прогресс |
| GET | `/api/updates/check` | Проверка GitHub Releases |
| POST | `/api/updates/apply` | Скачать и установить обновление |

## Сборка вручную (Windows)

```bat
pip install -r requirements-build.txt
python scripts\fetch_ffmpeg.py --platform windows-x64
pyinstaller packaging\VKVideoDownloader.spec --noconfirm --clean
```

Артефакт: `dist\VKVideoDownloader\`
