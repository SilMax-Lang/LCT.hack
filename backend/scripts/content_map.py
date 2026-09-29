"""Карта образовательного контента (ТЗ, раздел 5, п. 7) → docs/CONTENT_MAP.md.

Берёт задания из справочника `app/content/data/quests.json` (он сам
собирается из приложения скриптом sync_from_mobile.py), темы и практику —
прямо из Dart-кода приложения. Запуск из папки backend/:

    python scripts/content_map.py            # записать docs/CONTENT_MAP.md
    python scripts/content_map.py --check    # только проверить, что файл свежий
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUESTS = ROOT / "backend/app/content/data/quests.json"
LESSONS_DART = ROOT / "mobile/lib/data/lessons_data.dart"
MISSIONS_DART = ROOT / "mobile/lib/data/missions_data.dart"
OUT = ROOT / "docs/CONTENT_MAP.md"

TOPICS = {
    "budget": ("📋 Планирование бюджета", "планировать траты, расходы не больше доходов"),
    "savings": ("🐷 Сбережения и цель", "ставить цель и регулярно откладывать"),
    "purchases": ("🛒 Платежи и покупки", "отличать «надо» и «хочу», считать цену и сдачу"),
    "counting": ("🧮 Счёт с деньгами", "уверенно считать суммы, остаток и доли"),
}


def dart_topics() -> dict[str, str]:
    src = LESSONS_DART.read_text(encoding="utf-8")
    return dict(re.findall(r"'(\w+)': FinTopic\.(\w+),", src))


def dart_missions() -> list[dict[str, str]]:
    src = MISSIONS_DART.read_text(encoding="utf-8")
    missions = []
    for block in re.findall(r"Mission\((.*?)\n  \),", src, re.S):

        def field(name: str, text: str = block) -> str:
            m = re.search(rf"{name}: ((?:'[^']*'\s*)+)", text)
            parts = re.findall(r"'([^']*)'", m.group(1)) if m else []
            return "".join(parts).replace("$missionSaveDays", "3")

        topic = re.search(r"topic: FinTopic\.(\w+)", block)
        missions.append(
            {
                "id": field("id"),
                "topic": topic.group(1) if topic else "counting",
                "emoji": field("emoji"),
                "title": field("title"),
                "task": field("task"),
                "where": field("where"),
                "lesson": field("lesson"),
            }
        )
    return missions


def build() -> str:
    quests = json.loads(QUESTS.read_text(encoding="utf-8"))
    topics = dart_topics()
    tracks = {t["id"]: t for t in quests["tracks"]}
    lines = [
        "# Карта образовательного контента",
        "",
        "Тема, навык, ситуация, правильная логика и объяснение для ребёнка —",
        "по каждому заданию (ТЗ, раздел 5, п. 7). Файл **генерируется**",
        "из кода приложения: `python scripts/content_map.py` в папке `backend/`.",
        "",
        "Навыки взяты из приоритетных компетенций Единой рамки (ТЗ, раздел 1):",
        "бюджет и «расходы не больше доходов», «надо» и «хочу», покупки при",
        "ограниченном бюджете, цель и регулярные накопления, оценка своих решений.",
        "",
        "## Сводка",
        "",
        "| Тема | Навык | Заданий | Практика в игре |",
        "|---|---|---|---|",
    ]
    missions = dart_missions()
    for key, (title, skill) in TOPICS.items():
        count = sum(1 for q in quests["items"] if topics.get(q["id"], "counting") == key)
        prac = sum(1 for m in missions if m["topic"] == key)
        lines.append(f"| {title} | {skill} | {count} | {prac} |")
    lines += [
        "",
        f"Всего: {len(quests['items'])} заданий на дорогах и {len(missions)} "
        "заданий-действий («Практика в игре»).",
        "",
        "## Практика в игре",
        "",
        "Задания-действия: ребёнок делает настоящее действие в игре, игра",
        "засчитывает его сама (+10 🪙) и объясняет, почему это разумно.",
        "",
        "| Практика | Тема | Что сделать | Где | Объяснение после выполнения |",
        "|---|---|---|---|---|",
    ]
    for m in missions:
        lines.append(
            f"| {m['emoji']} {m['title']} | {TOPICS[m['topic']][0]} | {m['task']} "
            f"| {m['where']} | {m['lesson']} |"
        )
    for track_id in ("finance", "math"):
        track = tracks[track_id]
        lines += ["", f"## {track['emoji']} Дорога «{track['title']}»"]
        for section in track["sections"]:
            label = "уровень" if track_id == "finance" else "класс"
            lines += ["", f"### {section['grade']} {label}: {section['title']}"]
            for q in quests["items"]:
                if q["track"] != track_id or q["grade"] != section["grade"]:
                    continue
                title, skill = TOPICS[topics.get(q["id"], "counting")]
                right = q["options"][q["correct_index"]]
                lines += [
                    "",
                    f"**{q['emoji']} {q['title']}** (`{q['id']}`, " f"+{q['reward']['coins']} 🪙)",
                    "",
                    f"- Тема: {title} — {skill}",
                    f"- Ситуация: {q['question']}",
                    f"- Правильно: «{right}». {q['answer']}",
                    f"- Объяснение для ребёнка: {q['note']}",
                ]
    lines += [
        "",
        "## Как добавить задание",
        "",
        "Новое задание — один объект `Lesson(...)` в",
        "`mobile/lib/data/lessons_data.dart` и, если нужна тема, строка в",
        "`lessonTopics`. Логику и экраны менять не нужно (ТЗ 2.5.14). Потом",
        "`python scripts/sync_from_mobile.py` и `python scripts/content_map.py`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    text = build()
    if "--check" in sys.argv:
        if OUT.read_text(encoding="utf-8") != text:
            print("docs/CONTENT_MAP.md устарел: python scripts/content_map.py")
            return 1
        print("Карта контента актуальна.")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"Записано: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
