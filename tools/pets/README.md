# Скрипты для моделей питомцев

Превращают ролики Veo (питомец на зелёном фоне) в анимированные WebP с
прозрачностью и `pet.json` для `PetView`. Как и зачем — в
[docs/PET_DESIGN.md](../../docs/PET_DESIGN.md).

## Установка

```bash
pip install -r requirements.txt
```

Для `check_clip.py` нужен `ffprobe` (пакет ffmpeg).

## Скрипты

| Скрипт | Что делает |
|---|---|
| `check_clip.py` | проверка ролика до обработки: 1920×1080, чёрные полосы, касание края, отрыв лап, мусор на фоне, стык первого и последнего кадра |
| `pet_pipeline.py` | ролики одного питомца → `<state>.webp`, `<state>_poster.png`, `pet.json` (fps, кадры, точки склейки, трекинг головы) |
| `batch_pets.py` | вся папка исходников за один запуск; окраски без роликов делает перекраской |
| `recolor_images.py` | перекраска статичных картинок (базовых кадров) |
| `fit_head_eyes.py` | подбор рамки головы и контуров глаз для перекраски |

## Раскладка исходников

```
<root>/<пет>/<расцветка>/<возраст>/видео/idle.mp4, happy.mp4, hungry.mp4
<root>/<пет>/<расцветка>/<возраст>/картинки/head_px.txt, eyes_px.txt
  пет: кот | енот | пес   расцветка: рыжий | серый | чёрный   возраст: маленький | средний | большой
```

`head_px.txt` и `eyes_px.txt` — рамка головы и контуры глаз в пикселях
кадра ролика 1920×1080 (не зависят от кропа). Если их нет, скрипт откроет
окно выбора.

## Примеры

```bash
# проверить ролик
python check_clip.py idle.mp4 --sheet check.jpg

# один питомец
python pet_pipeline.py --pet cat_gray_medium --out out/normal \
  "idle=videos/idle.mp4" "happy=videos/happy.mp4" "hungry=videos/hungry.mp4" --preview

# перекраска серого в рыжего с масками глаз SAM и отчётом о пятнах
python pet_pipeline.py --pet cat_ginger_medium --out out/normal --recolor ginger --sam --qa \
  "idle=videos/idle.mp4" "happy=videos/happy.mp4"

# вся папка (обычное качество 512 px / 12 fps; both — ещё и 1024 px / 24 fps)
python batch_pets.py --root <папка исходников> --out out --quality normal --qa
python batch_pets.py --root <папка исходников> --out out --only cat --dry-run
```

## Частые проблемы

| Проблема | Что сделать |
|---|---|
| по краю шерсти зелёный ореол | `--key-lo 0.12` |
| шерсть полупрозрачная | `--key-lo 0.25` |
| в питомце есть зелёные детали | `--matte rembg` |
| файлы тяжёлые | `--size 384` или `--quality 75` |
| пауза на стыке цикла | первый и последний кадр в Flow должны быть одной картинкой |
