"""Тесты справочников.

Часть проверок намеренно повторяет минимальный объём контента из раздела 2.6
ТЗ: если аналитик уберёт задание или цель, тест упадёт раньше, чем это
увидит эксперт на демонстрации.
"""

import pytest

from app.content.library import ContentError, ContentLibrary, enforce_minimums
from app.core.config import settings

SECTIONS = {"catalog", "goals", "quests", "glossary", "pets", "economy"}


def test_content_loads_and_passes_minimums():
    """Сам факт загрузки означает, что контент прошёл проверки ТЗ 2.6."""
    library = ContentLibrary.load(settings.content_dir)

    assert library.content_version


def test_missing_content_breaks_startup():
    """Если аналитик уберёт задания, сервис не поднимется молча."""
    library = ContentLibrary.load(settings.content_dir)
    trimmed = library.quests.model_copy(update={"items": library.quests.items[:2]})

    with pytest.raises(ContentError, match="задания"):
        enforce_minimums(
            library.catalog,
            library.goals,
            trimmed,
            library.glossary,
            library.pets,
            library.economy,
        )


def test_manifest_lists_all_sections(client):
    body = client.get("/api/v1/content/manifest").json()

    assert body["content_version"]
    assert {section["name"] for section in body["sections"]} == SECTIONS
    assert all(section["etag"] for section in body["sections"])


def test_bundle_contains_every_section(client):
    body = client.get("/api/v1/content/bundle").json()
    manifest = client.get("/api/v1/content/manifest").json()

    assert SECTIONS <= set(body)
    assert body["content_version"] == manifest["content_version"]


def test_catalog_meets_required_minimum(client):
    body = client.get("/api/v1/content/catalog").json()
    items = body["items"]

    assert len(items) >= 8, "ТЗ 2.6: не менее 8 позиций покупок"
    assert sum(1 for item in items if item["kind"] == "mandatory") >= 5
    assert sum(1 for item in items if item["kind"] == "optional") >= 5
    assert all(len(item["title"]) <= 20 for item in items)
    assert all(item["price"] > 0 for item in items)
    assert body["deal_of_day"]["discount_percent"] == 30


def test_catalog_matches_app_shop(client):
    """Цены и эффекты — как в mobile/lib/data/shop_data.dart."""
    items = {item["id"]: item for item in client.get("/api/v1/content/catalog").json()["items"]}

    assert len(items) == 44
    assert items["milk"]["price"] == 10
    assert items["milk"]["effects"] == {"satiety": 20, "happiness": 0, "cleanliness": 0, "xp": 0}
    # Цены из документа «Игровая экономика».
    assert items["apple"]["price"] == 5
    assert items["ball"]["price"] == 15
    assert items["teddy"]["price"] == 30
    # Миска, поилка, лежанка — обязательные, покупаются навсегда.
    for item_id, price in {"bowl": 5, "drinker": 15, "bed": 50}.items():
        assert items[item_id]["price"] == price
        assert items[item_id]["kind"] == "mandatory"
        assert items[item_id]["permanent"] is True


def test_catalog_courses_and_decorations(client):
    body = client.get("/api/v1/content/catalog").json()
    items = body["items"]

    courses = [item for item in items if item["category"] == "education"]
    assert [c["price"] for c in courses] == [20, 40, 80, 160]
    assert [c["income_after"] for c in courses] == [60, 75, 95, 120]

    decorations = [item for item in items if item["category"] == "decorations"]
    by_rarity = {
        r: [d for d in decorations if d["rarity"] == r] for r in ("common", "rare", "epic")
    }
    assert len(decorations) == 20
    assert [len(by_rarity[r]) for r in ("common", "rare", "epic")] == [10, 6, 4]
    assert all(10 <= d["price"] <= 30 for d in by_rarity["common"])
    assert all(40 <= d["price"] <= 80 for d in by_rarity["rare"])
    assert all(100 <= d["price"] <= 200 for d in by_rarity["epic"])
    assert all(d["resale_price"] == round(d["price"] * 0.7) for d in decorations)

    rules = body["purchase_rules"]
    assert rules["requires_confirmation"] is True
    assert rules["hungry_block_at_satiety"] == 40
    blocked = {c["id"] for c in body["categories"] if c["blocked_when_hungry"]}
    assert blocked == {"toys", "education"}


def test_catalog_filters(client):
    optional = client.get("/api/v1/content/catalog", params={"kind": "optional"}).json()
    assert optional["items"]
    assert {item["kind"] for item in optional["items"]} == {"optional"}

    food = client.get("/api/v1/content/catalog", params={"category": "food"}).json()
    assert {item["category"] for item in food["items"]} == {"food"}


def test_catalog_item_by_id(client):
    assert client.get("/api/v1/content/catalog/apple").json()["title"] == "Яблочко"
    assert client.get("/api/v1/content/catalog/no_such_item").status_code == 404


def test_goals_meet_required_minimum(client):
    body = client.get("/api/v1/content/goals").json()
    items = body["items"]

    assert len(items) >= 3, "ТЗ 2.6: не менее 3 целей накопления"
    assert all(goal["price"] > 0 and goal["hint"] for goal in items)
    assert body["default_goal_id"] == "goal_bike"
    assert body["custom_goal"]["min_target"] == 50
    assert body["custom_goal"]["max_target"] == 5000


def test_goal_by_id(client):
    assert client.get("/api/v1/content/goals/goal_scooter").json()["price"] == 200
    assert client.get("/api/v1/content/goals/goal_spaceship").status_code == 404


def test_quests_meet_required_minimum(client):
    body = client.get("/api/v1/content/quests").json()
    items, tracks = body["items"], body["tracks"]

    assert len(items) >= 6, "ТЗ 2.6: не менее 6 заданий"
    assert {track["id"] for track in tracks} == {"math", "finance"}
    finance = next(track for track in tracks if track["id"] == "finance")
    assert len(finance["sections"]) >= 3, "ТЗ 2.5.8: минимум 3 темы"
    for lesson in items:
        assert len(lesson["options"]) == 4
        assert 0 <= lesson["correct_index"] < 4
        # ТЗ 2.5.8: объяснение выдаётся после ответа.
        assert lesson["answer"] and lesson["note"]
        # ТЗ 2.5.8: задания начисляют монеты, а не только очки.
        assert lesson["reward"]["coins"] == 5 + lesson["grade"] * 5


def test_quests_recovery_rule(client):
    """ТЗ 2.5.9: ошибка не отнимает прогресс, а даёт задачу «Повтори»."""
    rules = client.get("/api/v1/content/quests").json()["rules"]

    assert rules["mistake_goes_to_retry"] is True
    assert rules["mistake_penalty"] == 0


def test_quests_age_to_grade(client):
    rules = client.get("/api/v1/content/quests").json()["rules"]

    assert {row["age"]: row["grade"] for row in rules["age_to_grade"]} == {7: 1, 8: 2, 9: 3, 10: 4}
    # «Финансы»: 1–2 класс — 1 уровень, 3 класс — 2-й, 4 класс — 3-й.
    levels = {row["age"]: row["finance_level"] for row in rules["age_to_grade"]}
    assert levels == {7: 1, 8: 1, 9: 2, 10: 3}
    assert rules["rewarded_lessons_per_day"] == 2


def test_quests_filters(client):
    finance = client.get("/api/v1/content/quests", params={"track": "finance"}).json()
    assert finance["items"]
    assert {lesson["track"] for lesson in finance["items"]} == {"finance"}

    grade = client.get("/api/v1/content/quests", params={"track": "math", "grade": 4}).json()
    assert {(lesson["track"], lesson["grade"]) for lesson in grade["items"]} == {("math", 4)}


def test_quest_by_id(client):
    assert client.get("/api/v1/content/quests/fin_1_food").json()["reward"]["coins"] == 10
    assert client.get("/api/v1/content/quests/quest_budget_plan_60").status_code == 404


def test_pets_have_nine_combinations(client):
    body = client.get("/api/v1/content/pets").json()

    combinations = sum(len(species["variants"]) for species in body["species"])
    assert combinations >= 9, "ТЗ 2.6: 9+ комбинаций"
    assert len(body["name_suggestions"]) >= 5
    assert len(body["stages"]) >= 3, "ТЗ 2.6: не менее 3 стадий развития"
    assert [stage["title"] for stage in body["stages"]] == ["Малыш", "Ученик", "Исследователь"]
    assert [stage["min_level"] for stage in body["stages"]] == [1, 12, 35]
    assert (body["emotions"]["sad_below"], body["emotions"]["happy_above"]) == (33, 66)
    assert body["moods"][-1]["stat"] is None


def test_economy_rules(client):
    body = client.get("/api/v1/content/economy").json()

    assert body["period"]["demo_mode_periods"] >= 5, "ТЗ 2.6: 5 периодов подряд"
    assert body["rules"]["negative_balance_forbidden"] is True
    assert body["rules"]["savings_withdraw_requires_confirmation"] is True
    assert body["daily_bonus"]["coins"] == 15
    assert body["rules"]["purchase_requires_confirmation"] is True
    # Доход растёт от курсов: 50 → 60 → 75 → 95 → 120.
    assert [row["income"] for row in body["income"]["table"]] == [50, 60, 75, 95, 120]
    # Опыт: задание 5, конец дня 10, не больше 25 за день.
    assert {rule["id"]: rule["xp"] for rule in body["xp_rules"]} == {
        "lesson_solved": 5,
        "day_end": 10,
    }
    assert body["xp_per_day_max"] == 25
    deposit = body["savings"]["deposit"]
    assert (deposit["rate_per_year"], deposit["interest_cap"]) == (0.2, 500)
    assert body["streak"]["coins_bonus"] is True
    assert [(b["days"], b["coins"]) for b in body["streak"]["bonuses"]] == [
        (3, 10),
        (7, 20),
        (7, 10),
    ]
    assert body["budget_plan"]["steps"] == [5, 10]
    assert body["budget_plan"]["baskets"] == ["mandatory", "optional", "education", "savings"]


def test_glossary_not_empty(client):
    items = client.get("/api/v1/content/glossary").json()["items"]

    assert items, "ТЗ 2.5.11: нужен справочный раздел с терминами"
    assert all(term["definition"] for term in items)


def test_etag_returns_304(client):
    first = client.get("/api/v1/content/catalog")
    etag = first.headers["ETag"]

    second = client.get("/api/v1/content/catalog", headers={"If-None-Match": etag})

    assert first.status_code == 200
    assert second.status_code == 304
    assert second.content == b""


def test_filtered_response_has_its_own_etag(client):
    full = client.get("/api/v1/content/catalog").headers["ETag"]
    filtered = client.get("/api/v1/content/catalog", params={"kind": "optional"}).headers["ETag"]

    assert full != filtered

    # ETag от полного ответа не должен «подойти» к отфильтрованному.
    response = client.get(
        "/api/v1/content/catalog",
        params={"kind": "optional"},
        headers={"If-None-Match": full},
    )
    assert response.status_code == 200
