"""Синхронизация справочников бэкенда с приложением.

Источник правды для контента — Dart-код мобильного приложения (контент зашит
в `mobile/lib/data`, приложение работает офлайн). Скрипт читает константы
оттуда и пересобирает JSON в `app/content/data/`:

    catalog.json ← mobile/lib/data/shop_data.dart
    quests.json  ← mobile/lib/data/lessons_data.dart
    goals.json   ← mobile/lib/data/goals_data.dart
    pets.json    ← mobile/lib/models/pet.dart, data/names_data.dart
    economy.json ← константы mobile/lib/models/game_state.dart (+ блок from_documents)

Механики из документов команды (курсы, вклад, бонусы огонька, украшения,
план бюджета) теперь есть в приложении и читаются из кода. В блоке
`from_documents` остаётся только то, в чём приложение сознательно
отличается от документов (см. `FROM_DOCUMENTS`).

Запуск из каталога backend/:

    python scripts/sync_from_mobile.py          # перезаписать JSON
    python scripts/sync_from_mobile.py --check  # только сверить, код выхода 1 при расхождении
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
MOBILE = BACKEND.parent / "mobile" / "lib"
DATA = BACKEND / "app" / "content" / "data"

CONTENT_VERSION = "2.0.0"


# --------------------------------------------------------------------------
# Мини-парсер константных выражений Dart
# --------------------------------------------------------------------------


class Call(dict):
    """Вызов конструктора: `ShopItem(id: 'milk', …)` → Call(name='ShopItem', …)."""

    def __init__(self, name: str, args: list[Any], kwargs: dict[str, Any]) -> None:
        super().__init__(kwargs)
        self.name = name
        self.args = args


class Ref(str):
    """Ссылка на идентификатор: `ItemKind.food`."""


TOKEN = re.compile(
    r"""
    (?P<ws>\s+|//[^\n]*)
  | (?P<str>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
  | (?P<num>0x[0-9A-Fa-f]+|-?\d+(?:\.\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
  | (?P<punct>[\[\](){}:,<>])
  | (?P<other>.)
    """,
    re.VERBOSE,
)


def _tokens(source: str) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    while pos < len(source):
        match = TOKEN.match(source, pos)
        if match is None:
            raise ValueError(f"Не удалось разобрать Dart около: {source[pos:pos + 40]!r}")
        pos = match.end()
        kind = match.lastgroup
        if kind != "ws":
            tokens.append((kind, match.group()))
    return tokens


def _unquote(literal: str) -> str:
    body = literal[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


class _Parser:
    def __init__(self, source: str) -> None:
        self.tokens = _tokens(source)
        self.pos = 0

    def peek(self, offset: int = 0) -> tuple[str, str]:
        index = self.pos + offset
        return self.tokens[index] if index < len(self.tokens) else ("eof", "")

    def take(self, value: str | None = None) -> str:
        kind, text = self.peek()
        if value is not None and text != value:
            raise ValueError(f"Ожидалось {value!r}, встретилось {text!r}")
        self.pos += 1
        return text

    def value(self) -> Any:
        kind, text = self.peek()
        if kind == "str":
            parts = []
            while self.peek()[0] == "str":  # соседние литералы склеиваются
                parts.append(_unquote(self.take()))
            return "".join(parts)
        if kind == "num":
            self.take()
            return int(text, 16) if text.startswith("0x") else int(text)
        if text == "[":
            self.take("[")
            items = []
            while self.peek()[1] != "]":
                items.append(self.value())
                if self.peek()[1] == ",":
                    self.take(",")
            self.take("]")
            return items
        if text == "{":
            self.take("{")
            mapping = {}
            while self.peek()[1] != "}":
                key = self.value()
                self.take(":")
                mapping[key] = self.value()
                if self.peek()[1] == ",":
                    self.take(",")
            self.take("}")
            return mapping
        if kind == "ident":
            self.take()
            if text in ("true", "false"):
                return text == "true"
            if text == "null":
                return None
            if text == "const":
                return self.value()
            if self.peek()[1] == "(":
                return self._call(text)
            return Ref(text)
        raise ValueError(f"Неожиданный токен {text!r}")

    def _call(self, name: str) -> Call:
        self.take("(")
        args, kwargs = [], {}
        while self.peek()[1] != ")":
            if self.peek()[0] == "ident" and self.peek(1)[1] == ":":
                key = self.take()
                self.take(":")
                kwargs[key] = self.value()
            else:
                args.append(self.value())
            if self.peek()[1] == ",":
                self.take(",")
        self.take(")")
        return Call(name, args, kwargs)


def dart_const(source: str, name: str) -> Any:
    """Значение `const … name = <выражение>;`."""
    match = re.search(rf"\bconst\s+[\w<>, ]+?\s+{name}\s*=\s*", source)
    if match is None:
        raise ValueError(f"Константа {name} не найдена")
    return _Parser(source[match.end() :]).value()


def dart_int(source: str, pattern: str) -> int:
    match = re.search(pattern, source)
    if match is None:
        raise ValueError(f"В Dart-коде не найдено: {pattern}")
    return int(match.group(1))


def enum_values(source: str, enum: str) -> list[str]:
    match = re.search(rf"enum\s+{enum}\s*\{{([^}}]*)\}}", source)
    if match is None:
        raise ValueError(f"enum {enum} не найден")
    return [value.strip() for value in match.group(1).split(",") if value.strip()]


def switch_getter(source: str, extension: str, getter: str) -> dict[str, Any]:
    """`case Enum.value: return <литерал>;` внутри геттера расширения."""
    ext = re.search(rf"extension\s+\w+\s+on\s+{extension}\s*\{{", source)
    if ext is None:
        raise ValueError(f"extension on {extension} не найден")
    body = source[ext.end() :]
    start = re.search(rf"\bget\s+{getter}\s*\{{", body)
    if start is None:
        raise ValueError(f"{extension}.{getter} не найден")
    chunk = body[start.end() :]
    chunk = chunk[: chunk.index("\n  }")]
    result = {}
    for case, expr in re.findall(r"case\s+\w+\.(\w+):\s*return\s+(.+?);", chunk, re.S):
        result[case] = _Parser(expr).value()
    return result


def color(value: Call) -> str:
    argb = value.args[0]
    return f"#{argb & 0xFFFFFF:06X}"


def read(relative: str) -> str:
    return (MOBILE / relative).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Значения из документов команды (в коде приложения их нет)
# --------------------------------------------------------------------------

FROM_DOCUMENTS: dict[str, Any] = {
    "note": (
        "Отличия приложения от документов команды. Всё остальное из документов "
        "(курсы, вклад, бонусы огонька, украшения, план бюджета, подтверждение "
        "покупки, блок при голоде) реализовано и описано в основных разделах."
    ),
    "sources": ["Игровая_экономика_Финни_редакция.docx", "ТЗ_Питомец_Финни.docx"],
    "differences": [
        {
            "topic": "stages",
            "documents": "Малыш / Ученик / Исследователь по опыту: 0, 100, 200 XP",
            "app": "те же названия, этап по уровню питомца: 1–11, 12–34, 35+",
        },
        {
            "topic": "deposit_year",
            "documents": "проценты по вкладу при смене года",
            "app": "игровой год — 5 дней, чтобы проценты было видно в демо-режиме",
        },
    ],
}


# --------------------------------------------------------------------------
# Сборка разделов
# --------------------------------------------------------------------------

# Отделы магазина: ItemKind → id категории в API.
CATEGORY_IDS = {
    "food": "food",
    "hygiene": "hygiene",
    "health": "health",
    "home": "home",
    "fun": "toys",
    "education": "education",
    "decor": "decorations",
}

# Корзины бюджета по отделу (как BudgetBasket в приложении).
BASKETS = {"mandatory": "mandatory", "education": "education"}

# У готовых целей в приложении нет id — даём стабильные по названию.
GOAL_IDS = {
    "Домик для питомца": "goal_pet_house",
    "Самокат": "goal_scooter",
    "Велосипед": "goal_bike",
    "Поход в аквапарк": "goal_aquapark",
    "Железная дорога": "goal_railway",
    "Подарок маме": "goal_gift_mom",
}

STAGE_IDS = {"Малыш": "baby", "Ученик": "student", "Исследователь": "explorer"}


def _header(source: str) -> dict[str, Any]:
    return {
        "version": CONTENT_VERSION,
        "updated_at": date.today().isoformat(),
        "source": source,
    }


def _kinds_where(src: str, getter: str) -> set[str]:
    """ItemKind, перечисленные в геттере `bool get <getter> => this == ItemKind.x || …`."""
    body = re.search(rf"bool get {getter} =>(.*?);", src, re.S).group(1)
    return set(re.findall(r"ItemKind\.(\w+)", body))


def build_catalog() -> dict[str, Any]:
    src = read("data/shop_data.dart")
    kinds = enum_values(src, "ItemKind")
    titles = switch_getter(src, "ItemKind", "title")
    emojis = switch_getter(src, "ItemKind", "emoji")
    mandatory = _kinds_where(src, "mandatory")
    permanent = _kinds_where(src, "permanent")
    hungry_blocked = _kinds_where(src, "blockedWhenHungry")
    resale = float(re.search(r"const double resaleRate = ([\d.]+);", src).group(1))

    def basket(kind: str) -> str:
        if kind in mandatory:
            return "mandatory"
        return "education" if kind == "education" else "optional"

    categories = [
        {
            "id": CATEGORY_IDS[kind],
            "title": titles[kind],
            "emoji": emojis[kind],
            "kind": basket(kind),
            "permanent": kind in permanent,
            "blocked_when_hungry": kind in hungry_blocked,
        }
        for kind in kinds
    ]
    items = []
    for item in dart_const(src, "shopCatalog"):
        kind = item["kind"].split(".")[-1]
        rarity = item.get("rarity")
        items.append(
            {
                "id": item["id"],
                "title": item["title"],
                "category": CATEGORY_IDS[kind],
                "kind": basket(kind),
                "price": item["price"],
                "emoji": item["emoji"],
                "effects": {
                    "satiety": item.get("hunger", 0),
                    "happiness": item.get("happiness", 0),
                    "cleanliness": item.get("cleanliness", 0),
                },
                "effect_text": item["effectText"],
                "badge": item.get("badge"),
                "permanent": kind in permanent,
                "rarity": rarity.split(".")[-1] if rarity else None,
                "income_after": item.get("incomeAfter"),
                "resale_price": round(item["price"] * resale) if kind == "decor" else None,
            }
        )
    deal = re.search(r"pool\[\(day \* (\d+) \+ (\d+)\) % pool\.length\]", src)
    return {
        **_header("mobile/lib/data/shop_data.dart"),
        "categories": categories,
        "items": items,
        "deal_of_day": {
            "discount_percent": dart_int(src, r"const int dealPercent = (\d+);"),
            "day_multiplier": int(deal.group(1)),
            "day_offset": int(deal.group(2)),
            "min_price": dart_int(src, r"return price < (\d+) \?"),
            "explain": (
                "Товар дня — только из расходуемых (без вещей навсегда): "
                "pool[(day × 7 + 3) mod размер], цена со скидкой."
            ),
        },
        "purchase_rules": {
            "requires_confirmation": True,
            "hungry_block_at_satiety": dart_int(src, r"const int hungryBlockAt = (\d+);"),
            "hungry_block_message": (
                "{pet_name} слишком голоден, чтобы играть или учиться! Сначала накорми его."
            ),
            "courses_sequential": True,
            "start_income": dart_int(src, r"const int startIncome = (\d+);"),
            "decorations_resale_rate": resale,
            "decorations_sale_requires_confirmation": True,
        },
    }


def build_goals() -> dict[str, Any]:
    src = read("data/goals_data.dart")
    presets = dart_const(src, "goalPresets")
    default = dart_const(src, "defaultGoal")
    bank = read("screens/bank/goal_sheet.dart")
    return {
        **_header("mobile/lib/data/goals_data.dart"),
        "items": [
            {
                "id": GOAL_IDS[goal["title"]],
                "title": goal["title"],
                "emoji": goal["emoji"],
                "price": goal["price"],
                "hint": goal["hint"],
            }
            for goal in presets
        ],
        "default_goal_id": GOAL_IDS[default["title"]],
        "custom_goal": {
            "allowed": True,
            "min_target": dart_int(src, r"const int minGoalTarget = (\d+);"),
            "max_target": dart_int(src, r"const int maxGoalTarget = (\d+);"),
            "title_max_length": dart_int(bank, r"maxLength: (\d+)"),
            "emoji_choices": dart_const(src, "goalEmojiChoices"),
        },
    }


def build_quests() -> dict[str, Any]:
    src = read("data/lessons_data.dart")
    tracks = enum_values(src, "LessonTrack")
    titles = switch_getter(src, "LessonTrack", "title")
    emojis = switch_getter(src, "LessonTrack", "emoji")
    colors = switch_getter(src, "LessonTrack", "color")
    lessons = dart_const(src, "lessonsCatalog")
    reward = re.search(r"rewardForGrade\(int grade\) => (\d+) \+ grade \* (\d+);", src)
    base, per_grade = int(reward.group(1)), int(reward.group(2))
    xp = dart_int(src, r"const int lessonXp = (\d+);")
    age_offset = dart_int(src, r"return \(age - (\d+)\)\.clamp")
    per_day = dart_int(src, r"const int rewardedLessonsPerDay = (\d+);")

    def finance_grade(cls: int) -> int:
        return 1 if cls <= 2 else cls - 1

    # Названия разделов — из switch в sectionTitle:
    # финансы 1/2/остальные, математика 1/2/3/остальные.
    section = re.search(r"String sectionTitle\(int grade\) \{(.*?)\n  \}", src, re.S).group(1)
    finance_part, math_part = section.split("switch (grade)", 2)[1:]
    names = {
        "finance": re.findall(r"return '([^']+)';", finance_part),
        "math": re.findall(r"return '([^']+)';", math_part),
    }

    def section_title(track: str, grade: int) -> str:
        options = names[track]
        return options[min(grade, len(options)) - 1]

    track_list = []
    for track in tracks:
        grades = sorted({lesson["grade"] for lesson in lessons if lesson["track"].endswith(track)})
        track_list.append(
            {
                "id": track,
                "title": titles[track],
                "emoji": emojis[track],
                "color": color(colors[track]),
                "sections": [
                    {"grade": grade, "title": section_title(track, grade)} for grade in grades
                ],
            }
        )
    return {
        **_header("mobile/lib/data/lessons_data.dart"),
        "tracks": track_list,
        "rules": {
            "options_per_lesson": 4,
            "reward_base": base,
            "reward_per_grade": per_grade,
            "xp_per_lesson": xp,
            "reward_only_first_solve": True,
            "rewarded_lessons_per_day": per_day,
            "mistake_goes_to_retry": True,
            "mistake_penalty": 0,
            "age_to_grade": [
                {
                    "age": age,
                    "grade": age - age_offset,
                    "finance_level": finance_grade(age - age_offset),
                }
                for age in (7, 8, 9, 10)
            ],
            "age_to_grade_explain": (
                "Класс = возраст − 6 (10 — это «10+»): математика 1–4 класс. У финансов "
                "три уровня: 1–2 класс — 1 уровень, 3 класс — 2-й, 4 класс — 3-й."
            ),
        },
        "items": [
            {
                "id": lesson["id"],
                "track": lesson["track"].split(".")[-1],
                "grade": lesson["grade"],
                "title": lesson["title"],
                "emoji": lesson["emoji"],
                "question": lesson["question"],
                "options": lesson["options"],
                "correct_index": lesson["correct"],
                "answer": lesson["answer"],
                "note": lesson["note"],
                "reward": {"coins": base + lesson["grade"] * per_grade, "xp": xp},
            }
            for lesson in lessons
        ],
    }


def _pet_looks(src: str) -> list[dict[str, Any]]:
    """`PetLook(...)` в `PetLook.of` идут по порядку: кот v1–v3, собака v1–v3, пингвин v1–v3."""
    body = src[src.index("static PetLook of(") :]
    looks = []
    for match in re.finditer(r"PetLook\(", body):
        looks.append(_Parser(body[match.start() :]).value())
    return looks


def build_pets() -> dict[str, Any]:
    pet_src = read("models/pet.dart")
    names_src = read("data/names_data.dart")
    nickname_src = read("screens/onboarding/nickname_screen.dart")

    species = enum_values(pet_src, "PetType")
    variants = enum_values(pet_src, "PetVariant")
    titles = switch_getter(pet_src, "PetType", "title")
    emojis = switch_getter(pet_src, "PetType", "emoji")
    looks = iter(_pet_looks(pet_src))

    species_list = []
    for kind in species:
        species_list.append(
            {
                "id": kind,
                "title": titles[kind],
                "emoji": emojis[kind],
                "variants": [
                    {
                        "id": variant,
                        "title": look["label"],
                        "bg_start": color(look["bgStart"]),
                        "bg_end": color(look["bgEnd"]),
                        "accent": color(look["accent"]),
                    }
                    for variant, look in ((v, next(looks)) for v in variants)
                ],
            }
        )

    stage_titles = switch_getter(pet_src, "PetStage", "title")
    stages = [stage_titles[stage].split(" ", 1) for stage in enum_values(pet_src, "PetStage")]
    stage_levels = [
        1,
        dart_int(pet_src, r"const int teenLevel = (\d+);"),
        dart_int(pet_src, r"const int adultLevel = (\d+);"),
    ]
    sad_below = dart_int(pet_src, r"const int sadBelow = (\d+);")
    happy_above = dart_int(pet_src, r"const int happyAbove = (\d+);")

    mood_emoji = switch_getter(pet_src, "PetMood", "emoji")
    mood_phrase = switch_getter(pet_src, "PetMood", "phrase")
    mood_body = re.search(r"PetMood get mood \{(.*?)\n  \}", pet_src, re.S).group(1)
    urgent = re.findall(r"if \((\w+) <= (\d+)\) return PetMood\.(\w+);", mood_body)
    stat_ids = {"hunger": "satiety", "cleanliness": "cleanliness"}

    def mood(mood_id: str, stat: str | None, op: str | None, value: int | None) -> dict:
        return {
            "id": mood_id,
            "emoji": mood_emoji[mood_id],
            "phrase": mood_phrase[mood_id],
            "stat": stat,
            "op": op,
            "value": value,
        }

    # Сначала срочное (голод, умыться), потом эмоция по счастью, в конце — запасное.
    moods = [mood(m, stat_ids[stat], "lte", int(v)) for stat, v, m in urgent]
    moods += [
        mood("sad", "happiness", "lte", sad_below - 1),
        mood("joyful", "happiness", "gte", happy_above + 1),
        mood("calm", None, None, None),
    ]

    return {
        **_header("mobile/lib/models/pet.dart"),
        "species": species_list,
        "recolor_price": dart_int(
            read("models/game_state.dart"), r"const int recolorPrice = (\d+);"
        ),
        "stages": [
            {"id": STAGE_IDS[title], "title": title, "emoji": emoji, "min_level": level}
            for (title, emoji), level in zip(stages, stage_levels, strict=True)
        ],
        "emotions": {
            "stat": "happiness",
            "sad_below": sad_below,
            "happy_above": happy_above,
            "explain": (
                f"Эмоция модели по счастью: меньше {sad_below} — грустный, больше "
                f"{happy_above} — весёлый, между — обычный. У каждой свой ролик."
            ),
        },
        "moods": moods,
        "name_suggestions": dart_const(names_src, "dicePetNames"),
        "nickname_rules": {
            "min_length": 1,
            "max_length": dart_int(nickname_src, r"maxLength: (\d+)"),
            "trim_spaces": True,
            "profanity_filter": True,
            "hint": "До 15 символов, пробелы по краям убираются, грубые слова не пропускаются.",
        },
    }


def build_economy() -> dict[str, Any]:
    src = read("models/game_state.dart")
    shop = read("data/shop_data.dart")
    lessons = read("data/lessons_data.dart")
    bank = read("screens/bank/bank_screen.dart")
    profile = read("models/player_profile.dart")

    inventory = re.search(r"Map<String, int> inventory = \{([^}]*)\}", src).group(1)
    start_inventory = [
        {"item_id": item_id, "quantity": int(qty)}
        for item_id, qty in re.findall(r"'(\w+)': (\d+)", inventory)
    ]
    quick = re.search(r"children: \[([\d, ]+)\]\s*\.map", bank).group(1)
    start_income = dart_int(shop, r"const int startIncome = (\d+);")
    courses = [
        {
            "course_id": item["id"],
            "title": item["title"],
            "price": item["price"],
            "income_after": item["incomeAfter"],
        }
        for item in dart_const(shop, "shopCatalog")
        if item["kind"].endswith("education")
    ]
    streak_body = re.search(r"int streakBonusFor\(int streak\) \{(.*?)\n\}", src, re.S).group(1)
    streak_fixed = re.findall(r"if \(streak == (\d+)\) return (\d+);", streak_body)
    streak_repeat = re.search(r"streak % (\d+) == 0\) return (\d+);", streak_body)

    return {
        **_header("mobile/lib/models/game_state.dart"),
        "currency": {"code": "coin", "title": "монетка", "emoji": "🪙"},
        "start": {
            "balance": dart_int(src, r"int balance = (\d+);"),
            "inventory": start_inventory,
            "pet_level": 1,
            "pet_stats": 100,
            "day": 1,
        },
        "income": {
            "depends_on": "courses",
            "base": start_income,
            "explain": (
                f"Доход за день — {start_income} монет; каждый пройденный курс "
                "(магазин → «Обучение», по порядку) поднимает его."
            ),
            "table": [{"courses": 0, "income": start_income}]
            + [{"courses": i + 1, "income": c["income_after"]} for i, c in enumerate(courses)],
            "courses": courses,
            "sources": [
                {
                    "id": "day_income",
                    "title": "Доход за день",
                    "explain": "Начисляется кнопкой «Новый день», растёт с курсами.",
                },
                {
                    "id": "daily_bonus",
                    "title": "Бонус за возвращение",
                    "explain": "Первый вход за календарный день.",
                },
                {
                    "id": "lesson_reward",
                    "title": "Награда за задание",
                    "explain": "Первое верное решение, 10–25 монет, не больше 2 заданий в день.",
                },
                {
                    "id": "level_up",
                    "title": "Новый уровень питомца",
                    "explain": "Монетки за каждый новый уровень.",
                },
                {
                    "id": "streak_bonus",
                    "title": "Бонус огонька",
                    "explain": "3 и 7 дней подряд с действием, дальше каждые 7 дней.",
                },
                {
                    "id": "deposit_interest",
                    "title": "Проценты по вкладу",
                    "explain": "20 % копилки раз в игровой год (5 дней), не больше 500.",
                },
                {
                    "id": "decoration_sale",
                    "title": "Продажа украшения",
                    "explain": "Магазин выкупает украшение за 70 % цены.",
                },
                {
                    "id": "savings_withdraw",
                    "title": "Возврат из копилки",
                    "explain": "Не доход: монетки просто возвращаются в кошелёк.",
                },
            ],
        },
        "daily_bonus": {
            "coins": dart_int(src, r"const int dailyBonus = (\d+);"),
            "once_per": "calendar_day",
        },
        "level_up": {
            "xp_per_level": dart_int(src, r"while \(p\.xp >= (\d+)\)"),
            "coins_per_level": dart_int(src, r"const int levelUpCoins = (\d+);"),
            "restores_stats": True,
        },
        "xp_rules": [
            {
                "id": "lesson_solved",
                "xp": dart_int(lessons, r"const int lessonXp = (\d+);"),
                "explain": "Первое верное решение задания.",
            },
            {
                "id": "day_end",
                "xp": dart_int(src, r"const int endOfDayXp = (\d+);"),
                "explain": "Конец дня, до 10: 1 + по 3 за каждое решение дня — "
                "питомец сыт и чист (сытость и чистота больше 40), план "
                "подтверждён и выполнен, в копилку отложено.",
            },
        ],
        "xp_per_day_max": dart_int(src, r"const int maxXpPerDay = (\d+);"),
        "stats": [
            {
                "id": "satiety",
                "title": "Сытость",
                "emoji": "🍎",
                "max": 100,
                "decay_per_day": dart_int(src, r"const int dayHungerCost = (\d+);"),
                "low_threshold": 40,
            },
            {
                "id": "happiness",
                "title": "Счастье",
                "emoji": "😊",
                "max": 100,
                "decay_per_day": dart_int(src, r"const int dayHappinessCost = (\d+);"),
                "low_threshold": 33,
            },
            {
                "id": "cleanliness",
                "title": "Чистота",
                "emoji": "🧼",
                "max": 100,
                "decay_per_day": dart_int(src, r"const int dayCleanlinessCost = (\d+);"),
                "low_threshold": 40,
            },
        ],
        "period": {
            "title": "День",
            "advance": "manual_button",
            "skips_real_time": True,
            "demo_mode_periods": 5,
        },
        "savings": {
            "quick_amounts": [int(x) for x in quick.split(",")],
            "withdraw_amount": dart_int(bank, r"_withdraw\((\d+)\)"),
            "withdraw_requires_confirmation": True,
            "eta_average_days": dart_int(src, r"const int savingsAverageDays = (\d+);"),
            "deposit": {
                "rate_per_year": float(
                    re.search(r"const double depositRate = ([\d.]+);", src).group(1)
                ),
                "days_per_year": dart_int(src, r"const int daysPerYear = (\d+);"),
                "interest_cap": dart_int(src, r"const int interestCap = (\d+);"),
            },
        },
        "streak": {
            "counts": "Дни подряд, в которые было хотя бы одно действие: "
            "кормление, покупка, копилка или задание.",
            "resets_after_missed_day": True,
            "coins_bonus": True,
            "bonuses": [{"days": int(d), "coins": int(c), "repeat": False} for d, c in streak_fixed]
            + [
                {
                    "days": int(streak_repeat.group(1)),
                    "coins": int(streak_repeat.group(2)),
                    "repeat": True,
                }
            ],
        },
        "budget_plan": {
            "baskets": enum_values(shop, "BudgetBasket"),
            "steps": [
                dart_int(src, r"const int planStepSmall = (\d+);"),
                dart_int(src, r"const int planStepBig = (\d+);"),
            ],
            "confirm_locks_plan": True,
            "shows_plan_vs_fact": True,
            "new_plan_each_day": True,
            "unallocated_hint": (
                "У тебя осталось {amount} монеток. Может, добавим их в копилку на мечту?"
            ),
        },
        "player": {
            "min_age": dart_int(profile, r"static const int minAge = (\d+);"),
            "max_age": dart_int(profile, r"static const int maxAge = (\d+);"),
            "max_age_label": "10+",
        },
        "rules": {
            "negative_balance_forbidden": True,
            "purchase_requires_confirmation": True,
            "savings_withdraw_requires_confirmation": True,
            "quests_reward_coins": True,
            "mistake_creates_retry_task": True,
            "mistake_loses_progress": False,
        },
        "messages": {
            "goal_reached": "Цель «{goal}» накоплена! 🎉",
            "retry_lesson": "Попробуем задание ещё раз? 🔁",
            "lesson_waiting": "Реши задание — получишь монетки ⭐",
            "streak_unlit": (
                "Покорми питомца, реши задание или отложи монетки — и огонёк загорится."
            ),
        },
        "from_documents": FROM_DOCUMENTS,
    }


BUILDERS = {
    "catalog": build_catalog,
    "goals": build_goals,
    "quests": build_quests,
    "pets": build_pets,
    "economy": build_economy,
}


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _without_date(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "updated_at"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="только сверить, ничего не писать")
    options = parser.parse_args()

    stale = []
    for name, build in BUILDERS.items():
        payload = build()
        path = DATA / f"{name}.json"
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if _without_date(current) == _without_date(payload):
            continue
        stale.append(name)
        if not options.check:
            path.write_text(_dump(payload), encoding="utf-8")

    if options.check:
        if stale:
            print("Расходятся с приложением:", ", ".join(stale))
            return 1
        print("Справочники совпадают с приложением.")
        return 0
    print("Обновлены:", ", ".join(stale) if stale else "ничего — всё уже совпадает")
    return 0


if __name__ == "__main__":
    sys.exit(main())
