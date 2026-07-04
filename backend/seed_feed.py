# -*- coding: utf-8 -*-
"""Seed/editorial-публикации Ленты ИЗО ACA.

Импортирует изображения из папки-источника как публичные seed-публикации:
- оригинал сохраняется приватно в media/ (для истории/повтора/админки);
- сжатые деривативы feed_thumb (<=640) / feed_large (<=1600) WebP → media/feed;
- публикация: is_seed=1, author_type='editorial', prompt_visibility='hidden',
  реалистичные счётчики, даты за последние 30-45 дней, бейджи, face_template
  для izo (41).

Идемпотентно: удаляет прошлые seed-строки (is_seed=1) и media/feed деривативы
seed-публикаций перед импортом. Оригиналы seed (media/seed_izo_*) тоже
пересоздаются. Пользовательские публикации не трогаются.

Запуск (пример, стенд):
  DATABASE_URL=...  python seed_feed.py --source "C:\\...\\Изображения для ленты"
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import os
import random
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import main

SEED_USER = "seed_editorial"

# Пул авторов (handle, отображаемое имя). Аватарки назначаются циклически.
AUTHORS = [
    ("nova_render", "Nova Render"),
    ("mira_ai", "Мира"),
    ("deepframe", "DeepFrame"),
    ("artline", "ArtLine"),
    ("kseniya.visual", "Ксения"),
    ("pixel_smith", "Pixel Smith"),
    ("aurora_lab", "Aurora Lab"),
    ("mono_studio", "Mono Studio"),
    ("verakhud", "Вера"),
    ("neurograph", "Neurograph"),
    ("lucid_ai", "Lucid"),
    ("stanislav.art", "Станислав"),
    ("orbit_visual", "Orbit"),
    ("mari.frames", "Мари"),
]

# Пул названий (RU / EN) — раскидываются по работам.
TITLES = [
    ("Ночной город будущего", "Future night city"),
    ("Портрет в мягком свете", "Portrait in soft light"),
    ("Туман над горами", "Fog over the mountains"),
    ("Неоновый переулок", "Neon alley"),
    ("Тихая гавань на рассвете", "Quiet harbour at dawn"),
    ("Космическая станция", "Space station"),
    ("Лес после дождя", "Forest after the rain"),
    ("Стеклянный небоскрёб", "Glass skyscraper"),
    ("Девушка у окна", "Girl by the window"),
    ("Пустынный мираж", "Desert mirage"),
    ("Кибер-самурай", "Cyber samurai"),
    ("Морской бриз", "Sea breeze"),
    ("Старый маяк", "The old lighthouse"),
    ("Цветущий сад", "Blooming garden"),
    ("Заброшенный вокзал", "Abandoned station"),
    ("Зимнее утро", "Winter morning"),
    ("Портовый кран на закате", "Harbour crane at sunset"),
    ("Горная тропа", "Mountain trail"),
    ("Витрина парфюма", "Perfume showcase"),
    ("Фэнтези-замок", "Fantasy castle"),
    ("Ретро-автомобиль", "Retro car"),
    ("Дождливый мегаполис", "Rainy metropolis"),
]


def _rng_for(name: str) -> random.Random:
    return random.Random(int(hashlib.md5(name.encode()).hexdigest()[:8], 16))


def _aspect_kind(w: int, h: int) -> str:
    if not w or not h:
        return "square"
    if abs(w - h) / max(w, h) < 0.08:
        return "square"
    return "wide" if w > h else "tall"


def _clear_previous_seeds(conn) -> int:
    rows = conn.execute("SELECT id, image_id, feed_thumb_name, feed_large_name FROM feed_publications WHERE is_seed = 1").fetchall()
    for r in rows:
        for nm in (r["feed_thumb_name"], r["feed_large_name"]):
            if nm:
                f = (main.MEDIA / "feed" / nm)
                if f.exists():
                    try:
                        f.unlink()
                    except OSError:
                        pass
        # оригинал seed
        img = conn.execute("SELECT url FROM images WHERE id = ?", (r["image_id"],)).fetchone()
        nm = main._feed_media_name(img["url"]) if img else None
        if nm and nm.startswith("seed_izo_"):
            f = main.MEDIA / nm
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass
    conn.execute("DELETE FROM feed_publications WHERE is_seed = 1")
    conn.execute("DELETE FROM images WHERE user_id = ?", (SEED_USER,))
    return len(rows)


def _import_avatars(source: Path) -> list[str]:
    """Сжать аватарки в media/feed/avatars, вернуть список имён webp."""
    from PIL import Image, ImageOps

    avatars_src = source / "Аватарки"
    dest_dir = main.MEDIA / "feed" / "avatars"
    dest_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for p in sorted(avatars_src.glob("*.png")):
        idx = re.search(r"\((\d+)\)", p.name)
        out = f"ava_{int(idx.group(1)):02d}.webp" if idx else f"ava_{len(names):02d}.webp"
        try:
            with Image.open(p) as raw:
                img = ImageOps.exif_transpose(raw)
                w, h = img.size
                side = min(w, h)
                img = img.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
                img = img.resize((160, 160), Image.LANCZOS)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                img.save(dest_dir / out, format="WEBP", quality=82, method=6)
            names.append(out)
        except Exception as exc:  # noqa: BLE001
            print(f"  avatar skip {p.name}: {exc}")
    return names


def seed(source: Path) -> int:
    from PIL import Image

    files = sorted(
        glob.glob(str(source / "izo (*).png")),
        key=lambda f: int(re.search(r"\((\d+)\)", f).group(1)),
    )
    if not files:
        print(f"No izo (*).png in {source}")
        return 0

    (main.MEDIA / "feed").mkdir(parents=True, exist_ok=True)
    avatars = _import_avatars(source)
    if not avatars:
        avatars = [None]

    now = datetime.now(timezone.utc)
    with main.db() as conn:
        cleared = _clear_previous_seeds(conn)
        print(f"cleared {cleared} previous seed publications")
        created = 0
        for i, src in enumerate(files):
            fname = os.path.basename(src)
            num = int(re.search(r"\((\d+)\)", fname).group(1))
            rng = _rng_for(fname)
            with Image.open(src) as im:
                w, h = im.size
            kind = _aspect_kind(w, h)

            # оригинал приватно в media/
            orig_name = f"seed_izo_{num:02d}.png"
            shutil.copyfile(src, main.MEDIA / orig_name)

            image_id = f"seed-img-{num:02d}"
            pub_id = f"seed-pub-{num:02d}"

            # face template особый случай
            is_face = num == 41
            category = "face_template" if is_face else None

            # бейдж
            if is_face:
                badge = "face_template"
            elif rng.random() < 0.16:
                badge = "editor_pick"
            elif rng.random() < 0.24:
                badge = "trend"
            else:
                badge = None

            # реалистичные счётчики (выше для trend/editor_pick)
            boost = 2.4 if badge in ("trend", "editor_pick") else 1.0
            like_c = int(rng.randint(120, 1800) * boost)
            save_c = int(rng.randint(20, 380) * boost)
            recreate_c = int(rng.randint(3, 90) * boost)
            view_c = int(rng.randint(1500, 22000) * boost)

            # дата за 30-45 дней (шумно, чтобы не по номеру файла)
            days_ago = rng.uniform(0.2, 45.0)
            created_at = (now - timedelta(days=days_ago, hours=rng.uniform(0, 23))).isoformat()

            title_ru, title_en = TITLES[i % len(TITLES)]
            if is_face:
                title_ru, title_en = "Шаблон лица", "Face template"
            author_handle, author_display = AUTHORS[i % len(AUTHORS)]
            avatar = avatars[i % len(avatars)]

            settings = '{"styleName": null, "seed": %d}' % rng.randint(10000, 999999)
            conn.execute(
                "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, "
                "prompt_original, settings_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'image_to_image', 'comfyui', '', ?, ?)",
                (
                    image_id, SEED_USER, f"seed-{num}",
                    f"/api/media/{orig_name}?userId={SEED_USER}",
                    f"/api/media/{orig_name}?userId={SEED_USER}",
                    w, h, settings, created_at,
                ),
            )
            conn.execute(
                "INSERT INTO feed_publications "
                "(id, image_id, internal_user_id, legacy_user_id, title, description, "
                "prompt_visibility, allow_recreate, status, created_at, "
                "is_seed, author_type, author_handle, author_display, author_avatar, badge, category, "
                "base_like_count, base_save_count, base_recreate_count, view_count) "
                "VALUES (?, ?, ?, ?, ?, NULL, 'hidden', 1, 'published', ?, "
                "1, 'editorial', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pub_id, image_id, SEED_USER, SEED_USER, title_ru, created_at,
                    author_handle, author_display, avatar, badge, category,
                    like_c, save_c, recreate_c, view_c,
                ),
            )
            main.feed_build_derivatives(conn, pub_id, image_id)
            created += 1
        print(f"seeded {created} publications, {len(avatars)} avatars")
        return created


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=r"C:\Users\spike\Downloads\Изображения для ленты")
    args = ap.parse_args()
    n = seed(Path(args.source))
    print(f"DONE: {n} seed publications")
