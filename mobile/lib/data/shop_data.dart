import 'package:flutter/material.dart';

/// Каталог магазина (по документам «Игровая экономика» и «ТЗ Питомец Финни»).
///
/// Отделы делятся на корзины бюджета:
/// - «Надо» — еда, уход, здоровье и вещи для дома (миска, поилка, лежанка);
/// - «Хочу» — игрушки и украшения;
/// - «Обучение» — курсы, которые повышают доход за день.
///
/// Еда, уход, здоровье и игрушки — расходуемые: падают в рюкзачок и
/// тратятся на питомца. Вещи для дома, курсы и украшения покупаются
/// один раз и остаются навсегда (украшения можно продать за 70 %).
enum ItemKind { food, hygiene, health, home, fun, education, decor }

/// Корзина плана бюджета.
enum BudgetBasket { mandatory, optional, education, savings }

extension BudgetBasketInfo on BudgetBasket {
  String get title {
    switch (this) {
      case BudgetBasket.mandatory:
        return 'Надо';
      case BudgetBasket.optional:
        return 'Хочу';
      case BudgetBasket.education:
        return 'Обучение';
      case BudgetBasket.savings:
        return 'Копилка';
    }
  }

  String get emoji {
    switch (this) {
      case BudgetBasket.mandatory:
        return '🍎';
      case BudgetBasket.optional:
        return '🧸';
      case BudgetBasket.education:
        return '📚';
      case BudgetBasket.savings:
        return '🐷';
    }
  }

  Color get color {
    switch (this) {
      case BudgetBasket.mandatory:
        return const Color(0xFF43A047);
      case BudgetBasket.optional:
        return const Color(0xFF8E24AA);
      case BudgetBasket.education:
        return const Color(0xFF1E88E5);
      case BudgetBasket.savings:
        return const Color(0xFFF08A24);
    }
  }
}

extension ItemKindInfo on ItemKind {
  String get title {
    switch (this) {
      case ItemKind.food:
        return 'Еда';
      case ItemKind.hygiene:
        return 'Уход';
      case ItemKind.health:
        return 'Здоровье';
      case ItemKind.home:
        return 'Для дома';
      case ItemKind.fun:
        return 'Игрушки';
      case ItemKind.education:
        return 'Обучение';
      case ItemKind.decor:
        return 'Украшения';
    }
  }

  String get emoji {
    switch (this) {
      case ItemKind.food:
        return '🍎';
      case ItemKind.hygiene:
        return '🧼';
      case ItemKind.health:
        return '💊';
      case ItemKind.home:
        return '🏠';
      case ItemKind.fun:
        return '⚽';
      case ItemKind.education:
        return '📚';
      case ItemKind.decor:
        return '✨';
    }
  }

  /// Обязательная трата («надо») или нет.
  bool get mandatory =>
      this == ItemKind.food ||
      this == ItemKind.hygiene ||
      this == ItemKind.health ||
      this == ItemKind.home;

  /// Покупается один раз и остаётся навсегда.
  bool get permanent =>
      this == ItemKind.home ||
      this == ItemKind.education ||
      this == ItemKind.decor;

  /// Закрыто, пока питомец голоден (сытость ≤ [hungryBlockAt]).
  bool get blockedWhenHungry =>
      this == ItemKind.fun || this == ItemKind.education;

  BudgetBasket get basket {
    if (mandatory) return BudgetBasket.mandatory;
    if (this == ItemKind.education) return BudgetBasket.education;
    return BudgetBasket.optional;
  }
}

/// Редкость украшения.
enum Rarity { common, rare, epic }

extension RarityInfo on Rarity {
  String get title {
    switch (this) {
      case Rarity.common:
        return 'Обычное';
      case Rarity.rare:
        return 'Редкое';
      case Rarity.epic:
        return 'Эпическое';
    }
  }

  Color get color {
    switch (this) {
      case Rarity.common:
        return const Color(0xFF607D8B);
      case Rarity.rare:
        return const Color(0xFF1E88E5);
      case Rarity.epic:
        return const Color(0xFF8E24AA);
    }
  }

  /// Радость питомца от нового украшения.
  int get happiness {
    switch (this) {
      case Rarity.common:
        return 5;
      case Rarity.rare:
        return 10;
      case Rarity.epic:
        return 20;
    }
  }
}

class ShopItem {
  final String id;
  final String title;
  final String emoji;
  final int price;
  final ItemKind kind;

  /// Прирост статов: у расходуемых — при использовании из рюкзачка,
  /// у постоянных — один раз при покупке.
  final int hunger;
  final int happiness;
  final int cleanliness;
  final String effectText;

  /// Ярлык на карточке: «Хит», «Выгодно»…
  final String? badge;

  /// Редкость — только у украшений.
  final Rarity? rarity;

  /// Доход за день после курса — только у обучения.
  final int? incomeAfter;

  const ShopItem({
    required this.id,
    required this.title,
    required this.emoji,
    required this.price,
    required this.kind,
    this.hunger = 0,
    this.happiness = 0,
    this.cleanliness = 0,
    required this.effectText,
    this.badge,
    this.rarity,
    this.incomeAfter,
  });

  bool get mandatory => kind.mandatory;
  bool get permanent => kind.permanent;

  /// За сколько украшение выкупит магазин.
  int get resalePrice => (price * resaleRate).round();
}

/// Питомец голоден при сытости не выше этой — игрушки и обучение закрыты.
const int hungryBlockAt = 40;

/// Магазин выкупает украшения за 70 % цены.
const double resaleRate = 0.7;

/// Доход за день без курсов.
const int startIncome = 50;

/// Скидка дня в процентах.
const int dealPercent = 30;

/// Товар со скидкой — каждый день новый, только из расходуемых.
ShopItem dealOfDay(int day) {
  final pool = shopCatalog.where((i) => !i.permanent).toList();
  return pool[(day * 7 + 3) % pool.length];
}

int dealPrice(ShopItem item) {
  final price = (item.price * (100 - dealPercent) / 100).round();
  return price < 1 ? 1 : price;
}

ShopItem? itemById(String id) {
  for (final i in shopCatalog) {
    if (i.id == id) return i;
  }
  return null;
}

/// Курсы по порядку: следующий открывается после предыдущего.
List<ShopItem> get courses =>
    shopCatalog.where((i) => i.kind == ItemKind.education).toList();

/// Украшения коллекции.
List<ShopItem> get decorations =>
    shopCatalog.where((i) => i.kind == ItemKind.decor).toList();

const List<ShopItem> shopCatalog = [
  // ───── Еда ─────
  ShopItem(
    id: 'milk',
    title: 'Молочко',
    emoji: '🥛',
    price: 10,
    kind: ItemKind.food,
    hunger: 20,
    effectText: 'Вкусно! +20 к сытости 🥛',
  ),
  ShopItem(
    id: 'apple',
    title: 'Яблочко',
    emoji: '🍎',
    price: 5,
    kind: ItemKind.food,
    hunger: 15,
    effectText: 'Хрум-хрум! +15 к сытости 🍎',
  ),
  ShopItem(
    id: 'carrot',
    title: 'Морковка',
    emoji: '🥕',
    price: 6,
    kind: ItemKind.food,
    hunger: 10,
    effectText: 'Полезно и дёшево! +10 к сытости 🥕',
  ),
  ShopItem(
    id: 'cookie',
    title: 'Лакомство',
    emoji: '🍪',
    price: 20,
    kind: ItemKind.food,
    hunger: 25,
    happiness: 15,
    effectText: 'Ням! +25 к сытости и +15 к счастью 🍪',
    badge: 'Хит',
  ),
  ShopItem(
    id: 'fish',
    title: 'Рыбка',
    emoji: '🐟',
    price: 18,
    kind: ItemKind.food,
    hunger: 30,
    effectText: 'Свежая рыбка! +30 к сытости 🐟',
  ),
  ShopItem(
    id: 'dinner',
    title: 'Полноценный обед',
    emoji: '🍲',
    price: 25,
    kind: ItemKind.food,
    hunger: 50,
    effectText: 'Сытно! +50 к сытости 🍲',
    badge: 'Выгодно',
  ),

  // ───── Уход ─────
  ShopItem(
    id: 'soap',
    title: 'Мыло',
    emoji: '🧼',
    price: 10,
    kind: ItemKind.hygiene,
    cleanliness: 30,
    effectText: 'Чистота! +30 к чистоте 🧼',
  ),
  ShopItem(
    id: 'shower',
    title: 'Тёплый душ',
    emoji: '🚿',
    price: 15,
    kind: ItemKind.hygiene,
    cleanliness: 40,
    effectText: 'Свежесть! +40 к чистоте 🚿',
  ),
  ShopItem(
    id: 'bath',
    title: 'Ванна с пеной',
    emoji: '🛁',
    price: 20,
    kind: ItemKind.hygiene,
    cleanliness: 50,
    effectText: 'Пузырьки! +50 к чистоте 🛁',
  ),

  // ───── Здоровье ─────
  ShopItem(
    id: 'vitamins',
    title: 'Витамины',
    emoji: '💊',
    price: 20,
    kind: ItemKind.health,
    hunger: 10,
    happiness: 10,
    effectText: 'Бодрость! +10 к сытости и счастью 💊',
  ),
  ShopItem(
    id: 'tea',
    title: 'Тёплый чай',
    emoji: '🍵',
    price: 14,
    kind: ItemKind.health,
    hunger: 5,
    happiness: 10,
    effectText: 'Уютно! +10 к счастью 🍵',
  ),
  ShopItem(
    id: 'vet',
    title: 'Осмотр у ветврача',
    emoji: '🏥',
    price: 45,
    kind: ItemKind.health,
    hunger: 20,
    happiness: 20,
    cleanliness: 20,
    effectText: 'Здоров! +20 ко всему 🏥',
  ),

  // ───── Для дома: обязательные, покупаются один раз ─────
  ShopItem(
    id: 'bowl',
    title: 'Миска',
    emoji: '🥣',
    price: 5,
    kind: ItemKind.home,
    happiness: 5,
    effectText: 'Теперь есть из чего кушать!',
  ),
  ShopItem(
    id: 'drinker',
    title: 'Поилка',
    emoji: '🚰',
    price: 15,
    kind: ItemKind.home,
    happiness: 5,
    effectText: 'Свежая вода всегда рядом!',
  ),
  ShopItem(
    id: 'bed',
    title: 'Лежанка',
    emoji: '🛏️',
    price: 50,
    kind: ItemKind.home,
    happiness: 15,
    effectText: 'Сладкий сон на своём месте!',
  ),

  // ───── Игрушки ─────
  ShopItem(
    id: 'ball',
    title: 'Мячик',
    emoji: '⚽',
    price: 15,
    kind: ItemKind.fun,
    happiness: 20,
    effectText: 'Весело! +20 к счастью ⚽',
  ),
  ShopItem(
    id: 'balloon',
    title: 'Воздушный шарик',
    emoji: '🎈',
    price: 10,
    kind: ItemKind.fun,
    happiness: 15,
    effectText: 'Летит! +15 к счастью 🎈',
  ),
  ShopItem(
    id: 'paints',
    title: 'Краски',
    emoji: '🎨',
    price: 20,
    kind: ItemKind.fun,
    happiness: 25,
    effectText: 'Шедевр! +25 к счастью 🎨',
  ),
  ShopItem(
    id: 'teddy',
    title: 'Плюшевый мишка',
    emoji: '🧸',
    price: 30,
    kind: ItemKind.fun,
    happiness: 35,
    effectText: 'Обнимашки! +35 к счастью 🧸',
  ),
  ShopItem(
    id: 'board_game',
    title: 'Настольная игра',
    emoji: '🎲',
    price: 50,
    kind: ItemKind.fun,
    happiness: 50,
    effectText: 'Твой ход! +50 к счастью 🎲',
    badge: 'Новинка',
  ),

  // ───── Обучение: курсы по порядку, доход растёт ─────
  ShopItem(
    id: 'course_abc',
    title: 'Азбука финансов',
    emoji: '📘',
    price: 20,
    kind: ItemKind.education,
    incomeAfter: 60,
    effectText: 'Доход за день: 60 🪙',
  ),
  ShopItem(
    id: 'course_saver',
    title: 'Мастер накоплений',
    emoji: '📗',
    price: 40,
    kind: ItemKind.education,
    incomeAfter: 75,
    effectText: 'Доход за день: 75 🪙',
  ),
  ShopItem(
    id: 'course_future',
    title: 'Вклад в будущее',
    emoji: '📙',
    price: 80,
    kind: ItemKind.education,
    incomeAfter: 95,
    effectText: 'Доход за день: 95 🪙',
  ),
  ShopItem(
    id: 'course_math',
    title: 'Учебник математики',
    emoji: '📕',
    price: 160,
    kind: ItemKind.education,
    incomeAfter: 120,
    effectText: 'Доход за день: 120 🪙',
  ),

  // ───── Украшения: коллекция из 20 (10 обычных, 6 редких, 4 эпических) ─────
  ShopItem(
    id: 'decor_bow',
    title: 'Бантик',
    emoji: '🎀',
    price: 10,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_socks',
    title: 'Носочки',
    emoji: '🧦',
    price: 12,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_tulip',
    title: 'Тюльпан',
    emoji: '🌷',
    price: 14,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_sunflower',
    title: 'Подсолнух',
    emoji: '🌻',
    price: 16,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_chime',
    title: 'Колокольчик',
    emoji: '🎐',
    price: 18,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_rainbow',
    title: 'Радуга',
    emoji: '🌈',
    price: 20,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_star',
    title: 'Звёздочка',
    emoji: '⭐',
    price: 22,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_clover',
    title: 'Клевер',
    emoji: '🍀',
    price: 24,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_flags',
    title: 'Флажки',
    emoji: '🎏',
    price: 26,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_lamp',
    title: 'Ночник',
    emoji: '💡',
    price: 30,
    kind: ItemKind.decor,
    rarity: Rarity.common,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_hat',
    title: 'Шляпа',
    emoji: '🎩',
    price: 40,
    kind: ItemKind.decor,
    rarity: Rarity.rare,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_glasses',
    title: 'Очки',
    emoji: '🕶️',
    price: 48,
    kind: ItemKind.decor,
    rarity: Rarity.rare,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_backpack',
    title: 'Рюкзачок',
    emoji: '🎒',
    price: 55,
    kind: ItemKind.decor,
    rarity: Rarity.rare,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_lantern',
    title: 'Фонарик',
    emoji: '🏮',
    price: 62,
    kind: ItemKind.decor,
    rarity: Rarity.rare,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_violin',
    title: 'Скрипка',
    emoji: '🎻',
    price: 70,
    kind: ItemKind.decor,
    rarity: Rarity.rare,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_carousel',
    title: 'Карусель',
    emoji: '🎠',
    price: 80,
    kind: ItemKind.decor,
    rarity: Rarity.rare,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_crown',
    title: 'Корона',
    emoji: '👑',
    price: 100,
    kind: ItemKind.decor,
    rarity: Rarity.epic,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_castle',
    title: 'Замок',
    emoji: '🏰',
    price: 140,
    kind: ItemKind.decor,
    rarity: Rarity.epic,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_rocket',
    title: 'Ракета',
    emoji: '🚀',
    price: 170,
    kind: ItemKind.decor,
    rarity: Rarity.epic,
    effectText: 'В коллекцию!',
  ),
  ShopItem(
    id: 'decor_diamond',
    title: 'Алмаз',
    emoji: '💎',
    price: 200,
    kind: ItemKind.decor,
    rarity: Rarity.epic,
    effectText: 'В коллекцию!',
  ),
];
