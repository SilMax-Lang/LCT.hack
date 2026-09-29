import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../data/goals_data.dart';
import '../data/lessons_data.dart';
import '../data/missions_data.dart';
import '../data/shop_data.dart';
import '../services/name_filter.dart';
import 'pet.dart';
import 'player_profile.dart';

int _stat(int v) => v < 0 ? 0 : (v > 100 ? 100 : v);

// ───── Экономика (по документу «Игровая экономика Финни») ─────

/// Доход за день по числу пройденных курсов: 50 → 60 → 75 → 95 → 120.
int incomeForCourses(int coursesDone) {
  if (coursesDone <= 0) return startIncome;
  final list = courses;
  final i = math.min(coursesDone, list.length) - 1;
  return list[i].incomeAfter ?? startIncome;
}

/// Сколько монет даём за каждый новый уровень питомца.
const int levelUpCoins = 25;

/// Бонус за возвращение в новый календарный день.
const int dailyBonus = 15;

/// Сколько стоит перекрасить питомца в магазине.
const int recolorPrice = 40;

/// Сколько питомец «тратит» за прошедший день.
const int dayHungerCost = 15;
const int dayHappinessCost = 10;
const int dayCleanlinessCost = 12;

/// Опыт: за конец дня (максимум) и потолок опыта за один игровой день.
/// (За задание — [lessonXp].) Предметы и копилка опыта не дают.
const int endOfDayXp = 10;
const int maxXpPerDay = 25;

/// Опыт за прожитый день зависит от решений дня (ТЗ 2.5.10): питомец
/// сыт и чист, план выполнен, монетки отложены. 1 + 3 за каждое —
/// все три дают [endOfDayXp].
int periodXp(int checks) => 1 + 3 * checks.clamp(0, 3);

/// Сколько прошлых дней помним для средней суммы пополнения копилки.
const int savingsAverageDays = 5;

/// Подарок от взрослого: раз в игровой день.
const int parentGift = 20;

/// Вклад в копилке: 20 % за игровой год, не больше 500 за раз.
/// Игровой год — 5 дней: так проценты видно уже в демо-режиме.
const double depositRate = 0.2;
const int interestCap = 500;
const int daysPerYear = 5;

/// Бонус огонька за серию дней. После 7 дней — +10 каждые следующие 7.
int streakBonusFor(int streak) {
  if (streak == 3) return 10;
  if (streak == 7) return 20;
  if (streak > 7 && streak % 7 == 0) return 10;
  return 0;
}

/// Шаги плана бюджета.
const int planStepSmall = 5;
const int planStepBig = 10;

/// Событие «питомец вырос».
///
/// Награда начисляется сразу, а событие ждёт в [GameState.pendingLevelUp],
/// пока экран нового уровня его не заберёт: так он не потеряется, если
/// опыт прилетел из другого экрана.
class LevelUpEvent {
  final int fromLevel;
  final int toLevel;

  /// Монетки за рост — всего, если уровней набралось несколько.
  final int coins;

  const LevelUpEvent({
    required this.fromLevel,
    required this.toLevel,
    required this.coins,
  });

  int get levelsGained => toLevel - fromLevel;

  String get stageFrom => Pet.stageForLevel(fromLevel);
  String get stageTo => Pet.stageForLevel(toLevel);

  /// Сменился ли этап взросления — самый заметный результат роста.
  bool get stageChanged => stageFrom != stageTo;
}

/// Строка истории: откуда пришли или куда ушли монетки (ТЗ 2.5.4, 2.5.6:
/// баланс не меняется без объяснения, покупка остаётся в истории периода).
class JournalEntry {
  /// Игровой день, к которому относится запись.
  final int day;
  final String emoji;
  final String text;

  /// Изменение кошелька: + пришло, − ушло. 0 — только копилка.
  final int coins;

  /// Изменение копилки (+ отложили или проценты, − забрали).
  final int savings;

  const JournalEntry({
    required this.day,
    required this.emoji,
    required this.text,
    this.coins = 0,
    this.savings = 0,
  });

  Map<String, dynamic> toJson() => {
        'day': day,
        'emoji': emoji,
        'text': text,
        'coins': coins,
        'savings': savings,
      };

  static JournalEntry? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final day = raw['day'], text = raw['text'];
    if (day is! num || text is! String) return null;
    final coins = raw['coins'], savings = raw['savings'];
    final emoji = raw['emoji'];
    return JournalEntry(
      day: day.toInt(),
      emoji: emoji is String ? emoji : '•',
      text: text,
      coins: coins is num ? coins.toInt() : 0,
      savings: savings is num ? savings.toInt() : 0,
    );
  }
}

/// Итоги перехода к новому периоду — из них собирается «бумажка».
class DaySummary {
  final int day;

  /// Доход за день (зависит от курсов).
  final int income;

  /// Проценты по вкладу (0, если год ещё не прошёл).
  final int interest;

  /// Реальная просадка статов, а не номинальные «−15».
  final int hungerLost;
  final int happinessLost;
  final int cleanlinessLost;

  final int balance;
  final int savings;
  final String goalName;
  final int goalTarget;

  /// Решения прошедшего дня, от которых растёт питомец.
  final bool needsMet;
  final bool planConfirmed;
  final bool planKept;
  final bool saved;

  /// Сколько опыта принёс день (0, если упёрлись в потолок).
  final int growthXp;

  const DaySummary({
    required this.day,
    required this.income,
    this.interest = 0,
    required this.hungerLost,
    required this.happinessLost,
    required this.cleanlinessLost,
    required this.balance,
    required this.savings,
    required this.goalName,
    required this.goalTarget,
    this.needsMet = true,
    this.planConfirmed = false,
    this.planKept = false,
    this.saved = false,
    this.growthXp = 0,
  });

  int get goalLeft {
    final left = goalTarget - savings;
    return left < 0 ? 0 : left;
  }

  /// Следующий шаг: что исправить завтра (ТЗ 2.5.9 — путь восстановления).
  String get advice {
    if (!needsMet) {
      return 'Завтра сначала купи еду и уход — это «надо».';
    }
    if (!planConfirmed) {
      return 'Составь план на вкладке «План» — питомец вырастет быстрее.';
    }
    if (!planKept) {
      return 'Потрать на «хочу» не больше плана — или поменяй план завтра.';
    }
    if (!saved) {
      return 'Отложи хоть немного в копилку — цель станет ближе.';
    }
    return 'Отличный день! Так держать 💛';
  }

  Map<String, dynamic> toJson() => {
        'day': day,
        'income': income,
        'interest': interest,
        'hungerLost': hungerLost,
        'happinessLost': happinessLost,
        'cleanlinessLost': cleanlinessLost,
        'balance': balance,
        'savings': savings,
        'goalName': goalName,
        'goalTarget': goalTarget,
        'needsMet': needsMet,
        'planConfirmed': planConfirmed,
        'planKept': planKept,
        'saved': saved,
        'growthXp': growthXp,
      };

  static DaySummary? fromJson(Object? raw) {
    if (raw is! Map) return null;
    int n(String k) {
      final v = raw[k];
      return v is num ? v.toInt() : 0;
    }

    final goal = raw['goalName'];
    return DaySummary(
      day: n('day'),
      income: n('income'),
      interest: n('interest'),
      hungerLost: n('hungerLost'),
      happinessLost: n('happinessLost'),
      cleanlinessLost: n('cleanlinessLost'),
      balance: n('balance'),
      savings: n('savings'),
      goalName: goal is String ? goal : '',
      goalTarget: n('goalTarget'),
      needsMet: raw['needsMet'] != false,
      planConfirmed: raw['planConfirmed'] == true,
      planKept: raw['planKept'] == true,
      saved: raw['saved'] == true,
      growthXp: n('growthXp'),
    );
  }
}

/// Итог ответа на задание с дороги.
class LessonResult {
  final bool correct;

  /// Монеты начислены только за первое верное решение и не больше чем
  /// за [rewardedLessonsPerDay] заданий в день.
  final int reward;

  /// Задание уже было решено раньше — награды нет, это повторение.
  final bool alreadySolved;

  /// Решено впервые, но монеты за задания на сегодня уже получены.
  final bool dailyLimitReached;

  const LessonResult({
    required this.correct,
    required this.reward,
    required this.alreadySolved,
    this.dailyLimitReached = false,
  });
}

/// Результат покупки.
enum BuyResult { ok, noMoney, hungry, owned, locked }

/// Общее состояние игры: профиль, питомец, деньги, цель, задания,
/// рюкзачок, покупки навсегда, план бюджета, огонёк.
///
/// Живёт в одном ChangeNotifier и раздаётся через [GameStateScope]
/// (см. lib/app.dart). Сохраняется в SharedPreferences после изменений.
class GameState extends ChangeNotifier {
  static const _prefsKey = 'finny_state_v1';

  PlayerProfile? profile;
  Pet? pet;

  /// Монетки в кошельке.
  int balance = 60;

  /// Монетки в копилке (вклад).
  int savings = 0;
  String goalName = defaultGoal.title;
  String goalEmoji = defaultGoal.emoji;
  int goalTarget = defaultGoal.price;

  /// Текущий период («День N»).
  int day = 1;
  bool onboardingDone = false;

  /// Тёмная тема включена?
  bool isDark = false;

  /// Одноразовый флаг: только что прошли онбординг — показать «Секрет игры».
  bool justFinishedOnboarding = false;

  /// Расходуемые предметы в рюкзачке: id → количество.
  Map<String, int> inventory = {'milk': 1, 'soap': 1, 'ball': 1};

  /// Купленное навсегда: вещи для дома, курсы, украшения.
  Set<String> owned = {};

  /// Решённые задания и «Повтори» (задания, где была ошибка).
  Set<String> lessonsSolved = {};
  Set<String> lessonsRetry = {};

  /// Сколько всего было ошибок — для родительского режима.
  int lessonMistakes = 0;

  /// День последнего решённого задания (для подсказки «давно не решали»).
  int lessonGivenDay = 1;

  /// За сколько заданий сегодня уже дали монеты.
  int rewardedToday = 0;

  /// Сколько опыта питомец получил за сегодня (потолок [maxXpPerDay]).
  int xpToday = 0;

  /// Дата последнего ежедневного бонуса (yyyy-MM-dd).
  String? lastBonusDate;

  /// «Огонёк»: сколько дней подряд ребёнок что-то делал в игре.
  int streak = 0;

  /// Дата последнего действия (yyyy-MM-dd) — для подсчёта огонька.
  String? lastActionDate;

  /// Сколько процентов принёс вклад за всё время.
  int interestTotal = 0;

  // ───── План бюджета на день ─────

  /// Сколько монет было в начале дня — столько можно распределить.
  int planBudget = 60;

  /// План по корзинам и подтверждён ли он. После подтверждения план не
  /// меняется — только сравнение «план / факт».
  Map<BudgetBasket, int> plan = _emptyBaskets();
  bool planConfirmed = false;

  /// Факт за день: сколько реально ушло в каждую корзину.
  Map<BudgetBasket, int> fact = _emptyBaskets();

  static Map<BudgetBasket, int> _emptyBaskets() =>
      {for (final b in BudgetBasket.values) b: 0};

  /// Счётчик действий за сессию: по нему огонёк в шапке вспыхивает.
  int actionPulse = 0;

  /// Помощник в заданиях уже показывался (выезжает один раз).
  bool questsGuideSeen = false;

  /// Бонус, который ещё не показали на главной (плашкой), и его повод.
  int pendingBonus = 0;
  String pendingBonusText = '';

  /// Новый уровень, который ещё не показали ребёнку.
  LevelUpEvent? pendingLevelUp;

  /// История монеток: последние записи (текущий и прошлые дни).
  List<JournalEntry> journal = [];
  static const int _journalMax = 120;

  /// Выполненная практика и сколько разных дней ребёнок откладывал.
  Set<String> missionsDone = {};
  int saveDays = 0;
  int lastSaveDay = 0;

  /// Сколько отложено за последние дни — для среднего пополнения.
  List<int> savingsLog = [];

  /// Итоги последнего завершённого дня — для «Дневника».
  DaySummary? lastSummary;

  /// Анимации питомца и вспышки (ТЗ 3.6: анимации можно отключить).
  bool animationsOn = true;

  /// Игровой день последнего подарка от взрослого.
  int parentGiftDay = 0;

  // ───── Производные значения ─────

  int get coursesDone => courses.where((c) => owned.contains(c.id)).length;

  /// Доход за новый период. Растёт с курсами.
  int get baseIncome => incomeForCourses(coursesDone);

  /// Следующий курс, который можно купить (или null, если все пройдены).
  ShopItem? get nextCourse {
    for (final c in courses) {
      if (!owned.contains(c.id)) return c;
    }
    return null;
  }

  /// Питомец голоден — игрушки и обучение закрыты.
  bool get petHungry => (pet?.hunger ?? 100) <= hungryBlockAt;

  /// Сколько дней осталось до начисления процентов.
  int get daysToInterest {
    final r = day % daysPerYear;
    return r == 0 ? daysPerYear : daysPerYear - r;
  }

  /// Сколько принесёт вклад в конце года при нынешней копилке.
  int get expectedInterest =>
      math.min((savings * depositRate).floor(), interestCap);

  LevelUpEvent? consumeLevelUp() {
    final event = pendingLevelUp;
    pendingLevelUp = null;
    return event;
  }

  double get goalProgress {
    if (goalTarget <= 0) return 0;
    return (savings / goalTarget).clamp(0.0, 1.0);
  }

  int get goalLeft {
    final left = goalTarget - savings;
    return left < 0 ? 0 : left;
  }

  /// История текущего дня — новые записи сверху.
  List<JournalEntry> get todayJournal =>
      journal.where((e) => e.day == day).toList().reversed.toList();

  /// Средняя сумма пополнения копилки за день (ТЗ 2.5.7): по последним
  /// [savingsAverageDays] прожитым дням и сегодняшнему, если сегодня уже
  /// откладывали. 0 — пока не откладывали ни разу.
  int get avgDeposit {
    final today = fact[BudgetBasket.savings] ?? 0;
    final values = [...savingsLog, if (today > 0) today];
    if (values.isEmpty) return 0;
    final sum = values.fold<int>(0, (a, b) => a + b);
    if (sum <= 0) return 0;
    return (sum / values.length).ceil();
  }

  /// Сколько дней копить [left] монет при средней сумме пополнения.
  /// null — средней ещё нет (срок не считаем, а не выдумываем).
  int? daysToGoal(int left) {
    if (left <= 0) return 0;
    final avg = avgDeposit;
    if (avg <= 0) return null;
    return (left + avg - 1) ~/ avg;
  }

  bool get parentGiftAvailable => parentGiftDay != day;

  /// Следующее задание, которое советует Финни: сначала «Повтори»,
  /// потом — нерешённое своего уровня, потом — любое нерешённое.
  Lesson? get nextLesson {
    for (final id in lessonsRetry) {
      final lesson = lessonById(id);
      if (lesson != null) return lesson;
    }
    for (final track in LessonTrack.values) {
      final grade = recommendedGrade(age, track);
      for (final l in lessonsOf(track)) {
        if (l.grade == grade && !lessonsSolved.contains(l.id)) return l;
      }
    }
    for (final l in lessonsCatalog) {
      if (!lessonsSolved.contains(l.id)) return l;
    }
    return null;
  }

  int solvedOn(LessonTrack track) =>
      lessonsOf(track).where((l) => lessonsSolved.contains(l.id)).length;

  /// Цена предмета с учётом «скидки дня».
  int priceOf(ShopItem item) =>
      item.id == dealOfDay(day).id ? dealPrice(item) : item.price;

  String get nickname => profile?.nickname ?? 'Друг';

  int? get age => profile?.age;

  Future<void> init() => load();

  String _today() => DateTime.now().toIso8601String().substring(0, 10);

  // ───── Бонусы и огонёк ─────

  /// Ежедневный бонус. True — выдан (главная покажет плашку).
  bool claimDailyBonusIfNeeded() {
    if (!onboardingDone || pet == null) return false;
    if (lastBonusDate == _today()) return false;
    lastBonusDate = _today();
    balance += dailyBonus;
    _log('🎁', 'Бонус за вход в игру', coins: dailyBonus);
    _showBonus(dailyBonus, '${pet!.name} рад тебя видеть!');
    notifyListeners();
    save();
    return true;
  }

  void _showBonus(int amount, String text) {
    pendingBonus += amount;
    pendingBonusText = text;
  }

  /// Запись в историю: каждое изменение кошелька или копилки.
  void _log(String emoji, String text, {int coins = 0, int savings = 0}) {
    journal.add(JournalEntry(
      day: day,
      emoji: emoji,
      text: text,
      coins: coins,
      savings: savings,
    ));
    if (journal.length > _journalMax) {
      journal.removeRange(0, journal.length - _journalMax);
    }
  }

  /// Засчитать практику: +[missionReward] монет, запись в историю и
  /// плашка на главной с объяснением.
  void _completeMission(String id) {
    if (missionsDone.contains(id)) return;
    final mission = missionById(id);
    if (mission == null) return;
    missionsDone.add(id);
    balance += missionReward;
    _log('🧩', 'Практика «${mission.title}»', coins: missionReward);
    _showBonus(
      missionReward,
      '🧩 Практика «${mission.title}» выполнена! ${mission.lesson}',
    );
  }

  /// Подарок от взрослого (ТЗ 2.5.12: правила дополнительных баллов
  /// определяет команда): раз в игровой день, с подписью в истории.
  bool giveParentGift() {
    if (!parentGiftAvailable || pet == null) return false;
    parentGiftDay = day;
    balance += parentGift;
    _log('👨‍👩‍👧', 'Подарок от взрослого', coins: parentGift);
    _showBonus(parentGift, 'Подарок от взрослого!');
    notifyListeners();
    save();
    return true;
  }

  void setAnimations(bool on) {
    if (animationsOn == on) return;
    animationsOn = on;
    notifyListeners();
    save();
  }

  void markQuestsGuideSeen() {
    if (questsGuideSeen) return;
    questsGuideSeen = true;
    notifyListeners();
    save();
  }

  void dismissBonus() {
    if (pendingBonus == 0) return;
    pendingBonus = 0;
    pendingBonusText = '';
    notifyListeners();
  }

  /// Полезное действие: кормление, покупка, копилка, задание.
  /// Первое действие за календарный день продлевает огонёк; на 3-й и
  /// 7-й день подряд (и каждые следующие 7) — бонус монетами.
  void _registerAction() {
    actionPulse += 1;
    final today = _today();
    if (lastActionDate == today) return;
    final yesterday = DateTime.now()
        .subtract(const Duration(days: 1))
        .toIso8601String()
        .substring(0, 10);
    streak = lastActionDate == yesterday ? streak + 1 : 1;
    lastActionDate = today;
    final bonus = streakBonusFor(streak);
    if (bonus > 0) {
      balance += bonus;
      _log('🔥', 'Огонёк: $streak дн. подряд', coins: bonus);
      _showBonus(bonus, '🔥 Огонёк горит $streak дн. подряд!');
    }
  }

  bool get streakLitToday => lastActionDate == _today();

  // ───── Опыт ─────

  /// Начисляет опыт. С [capped] — не больше [maxXpPerDay] за день.
  /// Новый уровень: +25 монет, статы 100, событие для экрана роста.
  int _addXp(int amount, {bool capped = true}) {
    final p = pet;
    if (p == null || amount <= 0) return 0;
    final give = capped ? math.min(amount, maxXpPerDay - xpToday) : amount;
    if (give <= 0) return 0;
    if (capped) xpToday += give;

    final fromLevel = p.level;
    p.xp += give;
    while (p.xp >= 100) {
      p.xp -= 100;
      p.level += 1;
    }
    if (p.level != fromLevel) {
      final gained = p.level - fromLevel;
      final coins = levelUpCoins * gained;
      balance += coins;
      _log('⭐', 'Питомец вырос: уровень ${p.level}', coins: coins);
      p.hunger = 100;
      p.happiness = 100;
      p.cleanliness = 100;
      pendingLevelUp = LevelUpEvent(
        fromLevel: pendingLevelUp?.fromLevel ?? fromLevel,
        toLevel: p.level,
        coins: (pendingLevelUp?.coins ?? 0) + coins,
      );
    }
    return give;
  }

  // ───── Профиль ─────

  Future<void> createProfile({
    required String nickname,
    required int age,
    required PetType type,
    required PetVariant variant,
    required String petName,
  }) async {
    // Экраны онбординга уже не пускают мат, но сейв защищаем и здесь.
    profile = PlayerProfile(
      nickname: NameFilter.isAllowed(nickname) ? nickname : 'Игрок',
      age: age,
    );
    pet = Pet(
      type: type,
      variant: variant,
      name: NameFilter.isAllowed(petName) ? petName : 'Питомец',
      hunger: 100,
      happiness: 100,
      cleanliness: 100,
      xp: 0,
      level: 1,
    );
    _resetProgress();
    lastBonusDate = _today();
    onboardingDone = true;
    justFinishedOnboarding = true;
    notifyListeners();
    await save();
  }

  /// Всё игровое — к началу (профиль и тему не трогает).
  void _resetProgress() {
    balance = 60;
    savings = 0;
    goalName = defaultGoal.title;
    goalEmoji = defaultGoal.emoji;
    goalTarget = defaultGoal.price;
    day = 1;
    inventory = {'milk': 1, 'soap': 1, 'ball': 1};
    owned = {};
    lessonsSolved = {};
    lessonsRetry = {};
    lessonMistakes = 0;
    lessonGivenDay = 1;
    rewardedToday = 0;
    xpToday = 0;
    streak = 0;
    lastActionDate = null;
    interestTotal = 0;
    questsGuideSeen = false;
    pendingLevelUp = null;
    pendingBonus = 0;
    pendingBonusText = '';
    actionPulse = 0;
    journal = [];
    missionsDone = {};
    saveDays = 0;
    lastSaveDay = 0;
    savingsLog = [];
    lastSummary = null;
    parentGiftDay = 0;
    _startPlan();
    _log('👛', 'Стартовый бюджет', coins: balance);
  }

  /// Тестовый профиль для экспертов (ТЗ 2.5.13): готовый ребёнок 9 лет
  /// с рыжим котиком, прогресс — к исходному состоянию, онбординг
  /// пропускается. Повторный вызов — снова сброс к началу.
  Future<void> startTestProfile() => createProfile(
        nickname: 'Тестер',
        age: 9,
        type: PetType.cat,
        variant: PetVariant.v1,
        petName: 'Финни',
      );

  void _startPlan() {
    planBudget = balance;
    plan = _emptyBaskets();
    fact = _emptyBaskets();
    planConfirmed = false;
  }

  void updateAge(int age) {
    final p = profile;
    if (p == null || !PlayerProfile.isValidAge(age)) return;
    profile = p.copyWith(age: age);
    notifyListeners();
    save();
  }

  void toggleTheme() {
    isDark = !isDark;
    notifyListeners();
    save();
  }

  // ───── Магазин ─────

  /// Можно ли купить и почему нет (для подсказки на кнопке).
  BuyResult canBuy(ShopItem item) {
    if (item.permanent && owned.contains(item.id)) return BuyResult.owned;
    if (item.kind == ItemKind.education && nextCourse?.id != item.id) {
      return BuyResult.locked;
    }
    if (item.kind.blockedWhenHungry && petHungry) return BuyResult.hungry;
    if (balance < priceOf(item)) return BuyResult.noMoney;
    return BuyResult.ok;
  }

  /// Купить. Расходуемое — в рюкзачок; постоянное — навсегда, эффект сразу.
  BuyResult buyItem(String itemId) {
    final item = itemById(itemId);
    if (item == null) return BuyResult.locked;
    final check = canBuy(item);
    if (check != BuyResult.ok) return check;
    final price = priceOf(item);
    final isDeal = item.id == dealOfDay(day).id;
    balance -= price;
    fact[item.kind.basket] = (fact[item.kind.basket] ?? 0) + price;
    _log(item.emoji, 'Покупка: ${item.title} (${item.kind.basket.title})',
        coins: -price);
    if (item.permanent) {
      owned.add(item.id);
      final p = pet;
      if (p != null) {
        final joy = item.happiness + (item.rarity?.happiness ?? 0);
        p.happiness = _stat(p.happiness + joy);
      }
    } else {
      inventory[itemId] = (inventory[itemId] ?? 0) + 1;
    }
    _registerAction();
    if (item.mandatory) _completeMission('m_need_first');
    if (isDeal) _completeMission('m_deal');
    notifyListeners();
    save();
    return BuyResult.ok;
  }

  /// Продать украшение за 70 % цены.
  bool sellDecoration(String itemId) {
    final item = itemById(itemId);
    if (item == null || item.kind != ItemKind.decor) return false;
    if (!owned.remove(itemId)) return false;
    balance += item.resalePrice;
    _log(item.emoji, 'Продажа: ${item.title}', coins: item.resalePrice);
    notifyListeners();
    save();
    return true;
  }

  /// Перекрасить питомца. Та же окраска — ничего не меняется.
  bool recolorPet(PetVariant variant) {
    final p = pet;
    if (p == null) return false;
    if (p.variant == variant) return true;
    if (balance < recolorPrice) return false;
    balance -= recolorPrice;
    fact[BudgetBasket.optional] =
        (fact[BudgetBasket.optional] ?? 0) + recolorPrice;
    _log('🎨', 'Перекраска питомца (хочу)', coins: -recolorPrice);
    p.variant = variant;
    _registerAction();
    notifyListeners();
    save();
    return true;
  }

  /// Использовать предмет из рюкзачка. Текст эффекта или null.
  String? useItem(String itemId) {
    final count = inventory[itemId] ?? 0;
    final p = pet;
    final item = itemById(itemId);
    if (count <= 0 || p == null || item == null) return null;
    inventory[itemId] = count - 1;
    p.hunger = _stat(p.hunger + item.hunger);
    p.happiness = _stat(p.happiness + item.happiness);
    p.cleanliness = _stat(p.cleanliness + item.cleanliness);
    _registerAction();
    notifyListeners();
    save();
    return item.effectText;
  }

  // ───── Копилка (вклад) ─────

  bool deposit(int amount) {
    if (amount <= 0 || balance < amount) return false;
    balance -= amount;
    savings += amount;
    fact[BudgetBasket.savings] = (fact[BudgetBasket.savings] ?? 0) + amount;
    _log('🐷', 'В копилку', coins: -amount, savings: amount);
    if (lastSaveDay != day) {
      lastSaveDay = day;
      saveDays += 1;
    }
    _registerAction();
    _completeMission('m_first_save');
    if (saveDays >= missionSaveDays) _completeMission('m_save_3');
    notifyListeners();
    save();
    return true;
  }

  bool withdraw(int amount) {
    if (amount <= 0 || savings < amount) return false;
    savings -= amount;
    balance += amount;
    final saved = fact[BudgetBasket.savings] ?? 0;
    fact[BudgetBasket.savings] = math.max(0, saved - amount);
    _log('🐷', 'Из копилки в кошелёк', coins: amount, savings: -amount);
    notifyListeners();
    save();
    return true;
  }

  bool updateGoal(String name, int target, {String? emoji}) {
    final trimmed = name.trim();
    if (trimmed.isEmpty || target < minGoalTarget || target > maxGoalTarget) {
      return false;
    }
    goalName = trimmed;
    goalTarget = target;
    if (emoji != null && emoji.isNotEmpty) goalEmoji = emoji;
    notifyListeners();
    save();
    return true;
  }

  // ───── План бюджета ─────

  int get planned => plan.values.fold(0, (a, b) => a + b);
  int get unplanned => math.max(0, planBudget - planned);

  /// Изменить корзину на [delta] (шаги 5/10). Только до подтверждения,
  /// корзина не уходит в минус, сумма — не больше бюджета дня.
  bool changePlan(BudgetBasket basket, int delta) {
    if (planConfirmed) return false;
    final current = plan[basket] ?? 0;
    var next = current + delta;
    if (next < 0) next = 0;
    if (delta > 0) next = math.min(next, current + unplanned);
    if (next == current) return false;
    plan[basket] = next;
    notifyListeners();
    save();
    return true;
  }

  /// Подтвердить план — дальше только сравнение «план / факт».
  void confirmPlan() {
    if (planConfirmed) return;
    planConfirmed = true;
    final threeWays = (plan[BudgetBasket.mandatory] ?? 0) > 0 &&
        (plan[BudgetBasket.optional] ?? 0) > 0 &&
        (plan[BudgetBasket.savings] ?? 0) > 0;
    if (threeWays) _completeMission('m_plan');
    notifyListeners();
    save();
  }

  // ───── Задания ─────

  /// Ответ на задание. Верно впервые — опыт и (не больше 2 раз в день)
  /// монеты. Ошибка ничего не отнимает: задание становится «Повтори».
  LessonResult answerLesson(String id, int choice) {
    final lesson = lessonById(id);
    if (lesson == null) {
      return const LessonResult(correct: false, reward: 0, alreadySolved: false);
    }
    final already = lessonsSolved.contains(id);
    final correct = choice == lesson.correct;
    var reward = 0;
    var limited = false;
    if (correct) {
      lessonsRetry.remove(id);
      if (!already) {
        lessonsSolved.add(id);
        if (rewardedToday < rewardedLessonsPerDay) {
          reward = lesson.reward;
          balance += reward;
          rewardedToday += 1;
          _log(lesson.emoji, 'Задание «${lesson.title}»', coins: reward);
        } else {
          limited = true;
        }
        _addXp(lessonXp);
        lessonGivenDay = day;
      }
      _registerAction();
    } else if (!already) {
      lessonsRetry.add(id);
      lessonMistakes += 1;
    }
    notifyListeners();
    save();
    return LessonResult(
      correct: correct,
      reward: reward,
      alreadySolved: already,
      dailyLimitReached: limited,
    );
  }

  void resetLessons() {
    lessonsSolved = {};
    lessonsRetry = {};
    lessonMistakes = 0;
    lessonGivenDay = day;
    notifyListeners();
    save();
  }

  // ───── Новый день ─────

  /// Переход к следующему периоду: опыт за день, доход, проценты раз в
  /// игровой год, траты питомца, новый план бюджета.
  DaySummary nextDay() {
    // Итоги решений уходящего дня (ТЗ 2.5.10): от них зависит рост.
    final p0 = pet;
    final needsMet = p0 == null ||
        (p0.hunger > hungryBlockAt && p0.cleanliness > hungryBlockAt);
    final savedToday = fact[BudgetBasket.savings] ?? 0;
    final saved = savedToday > 0;
    final planKept = planConfirmed &&
        (fact[BudgetBasket.optional] ?? 0) <=
            (plan[BudgetBasket.optional] ?? 0) &&
        (fact[BudgetBasket.education] ?? 0) <=
            (plan[BudgetBasket.education] ?? 0) &&
        savedToday >= (plan[BudgetBasket.savings] ?? 0);
    final checks = [needsMet, planKept, saved].where((ok) => ok).length;
    if (planKept) _completeMission('m_plan_kept');
    savingsLog = [...savingsLog, savedToday];
    if (savingsLog.length > savingsAverageDays) {
      savingsLog = savingsLog.sublist(savingsLog.length - savingsAverageDays);
    }

    // Опыт за прожитый день — в счёт уходящего дня (с его потолком).
    final growthXp = _addXp(periodXp(checks));

    final income = baseIncome;
    day += 1;
    balance += income;
    _log('🪙', 'Доход за день', coins: income);

    var interest = 0;
    if (day % daysPerYear == 0 && savings > 0) {
      interest = expectedInterest;
      savings += interest;
      interestTotal += interest;
      _log('🏦', 'Проценты по вкладу (в копилку)', savings: interest);
    }

    var hungerLost = 0;
    var happinessLost = 0;
    var cleanlinessLost = 0;
    final p = pet;
    if (p != null) {
      final h = p.hunger, j = p.happiness, c = p.cleanliness;
      p.hunger = _stat(p.hunger - dayHungerCost);
      p.happiness = _stat(p.happiness - dayHappinessCost);
      p.cleanliness = _stat(p.cleanliness - dayCleanlinessCost);
      hungerLost = h - p.hunger;
      happinessLost = j - p.happiness;
      cleanlinessLost = c - p.cleanliness;
    }

    rewardedToday = 0;
    xpToday = 0;
    final wasConfirmed = planConfirmed;
    _startPlan();
    final summary = DaySummary(
      day: day,
      income: income,
      interest: interest,
      hungerLost: hungerLost,
      happinessLost: happinessLost,
      cleanlinessLost: cleanlinessLost,
      balance: balance,
      savings: savings,
      goalName: goalName,
      goalTarget: goalTarget,
      needsMet: needsMet,
      planConfirmed: wasConfirmed,
      planKept: planKept,
      saved: saved,
      growthXp: growthXp,
    );
    lastSummary = summary;
    notifyListeners();
    save();
    return summary;
  }

  /// Одна короткая подсказка Финни для главного экрана или null.
  /// Состояние питомца видно по нему самому, здесь — чего по нему не видно.
  String? finnyTip() {
    final p = pet;
    if (p == null) return null;
    if (goalProgress >= 1) return 'Цель «$goalName» накоплена! 🎉';
    for (final item in shopCatalog) {
      if (item.kind == ItemKind.home && !owned.contains(item.id)) {
        return '${item.emoji} ${item.title} — обязательная вещь. Загляни в магазин!';
      }
    }
    if (lessonsRetry.isNotEmpty) return 'Попробуем задание ещё раз? 🔁';
    if (nextLesson != null && day - lessonGivenDay > 1) {
      return 'Реши задание — получишь монетки ⭐';
    }
    return null;
  }

  // ───── Режим разработчика и эксперта ─────

  /// Опыт без прокрутки дней (без дневного потолка).
  void devAddXp(int amount) {
    _addXp(amount, capped: false);
    notifyListeners();
    save();
  }

  void devAddCoins(int amount) {
    balance += amount;
    _log('🧪', 'Режим эксперта', coins: amount);
    notifyListeners();
    save();
  }

  void devRestorePet() => _devStats(100, 100, 100);
  void devDrainPet() => _devStats(10, 10, 10);

  void _devStats(int hunger, int happiness, int cleanliness) {
    final p = pet;
    if (p == null) return;
    p.hunger = hunger;
    p.happiness = happiness;
    p.cleanliness = cleanliness;
    notifyListeners();
    save();
  }

  /// Сразу поставить уровень (без наград) — посмотреть модель этапа.
  void devSetLevel(int level) {
    final p = pet;
    if (p == null || level < 1) return;
    p.level = level;
    p.xp = 0;
    pendingLevelUp = null;
    notifyListeners();
    save();
  }

  void devSetHappiness(int value) {
    final p = pet;
    if (p == null) return;
    p.happiness = _stat(value);
    notifyListeners();
    save();
  }

  void devSkipDays(int days) {
    for (var i = 0; i < days; i++) {
      nextDay();
    }
  }

  void devSolveAllLessons() {
    lessonsSolved = {for (final l in lessonsCatalog) l.id};
    lessonsRetry = {};
    notifyListeners();
    save();
  }

  void devResetGuide() {
    questsGuideSeen = false;
    notifyListeners();
    save();
  }

  /// +1 день к огоньку (с бонусом, если серия до него дошла).
  void devBumpStreak() {
    streak += 1;
    lastActionDate = _today();
    actionPulse += 1;
    final bonus = streakBonusFor(streak);
    if (bonus > 0) {
      balance += bonus;
      _log('🔥', 'Огонёк: $streak дн. подряд', coins: bonus);
      _showBonus(bonus, '🔥 Огонёк горит $streak дн. подряд!');
    }
    notifyListeners();
    save();
  }

  // ───── Сохранение ─────

  Map<String, int> _basketsToJson(Map<BudgetBasket, int> m) =>
      {for (final e in m.entries) e.key.name: e.value};

  Map<BudgetBasket, int> _basketsFromJson(Object? raw) {
    final result = _emptyBaskets();
    if (raw is Map) {
      for (final b in BudgetBasket.values) {
        final v = raw[b.name];
        if (v is num && v >= 0) result[b] = v.toInt();
      }
    }
    return result;
  }

  Future<void> save() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final data = <String, dynamic>{
        'profile': profile?.toJson(),
        'pet': pet?.toJson(),
        'balance': balance,
        'savings': savings,
        'goalName': goalName,
        'goalEmoji': goalEmoji,
        'goalTarget': goalTarget,
        'day': day,
        'onboardingDone': onboardingDone,
        'isDark': isDark,
        'inventory': inventory,
        'owned': owned.toList(),
        'lessonsSolved': lessonsSolved.toList(),
        'lessonsRetry': lessonsRetry.toList(),
        'lessonMistakes': lessonMistakes,
        'lessonGivenDay': lessonGivenDay,
        'rewardedToday': rewardedToday,
        'xpToday': xpToday,
        'lastBonusDate': lastBonusDate,
        'streak': streak,
        'lastActionDate': lastActionDate,
        'interestTotal': interestTotal,
        'questsGuideSeen': questsGuideSeen,
        'planBudget': planBudget,
        'plan': _basketsToJson(plan),
        'planConfirmed': planConfirmed,
        'fact': _basketsToJson(fact),
        'journal': [for (final e in journal) e.toJson()],
        'missionsDone': missionsDone.toList(),
        'saveDays': saveDays,
        'lastSaveDay': lastSaveDay,
        'savingsLog': savingsLog,
        'lastSummary': lastSummary?.toJson(),
        'animationsOn': animationsOn,
        'parentGiftDay': parentGiftDay,
      };
      await prefs.setString(_prefsKey, jsonEncode(data));
    } catch (_) {
      // Ошибка сохранения не должна ронять игру.
    }
  }

  Future<void> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_prefsKey);
      if (raw == null || raw.isEmpty) return;
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) return;

      final profileJson = decoded['profile'];
      if (profileJson is Map<String, dynamic>) {
        profile = PlayerProfile.fromJson(profileJson);
      }
      final petJson = decoded['pet'];
      if (petJson is Map<String, dynamic>) pet = Pet.fromJson(petJson);

      int readInt(String key, int fallback) {
        final v = decoded[key];
        return v is num ? v.toInt() : fallback;
      }

      balance = math.max(0, readInt('balance', 60));
      savings = math.max(0, readInt('savings', 0));
      final g = decoded['goalName'];
      if (g is String && g.isNotEmpty) goalName = g;
      final ge = decoded['goalEmoji'];
      if (ge is String && ge.isNotEmpty) goalEmoji = ge;
      goalTarget = readInt('goalTarget', defaultGoal.price);
      day = readInt('day', 1);
      onboardingDone = decoded['onboardingDone'] == true;
      isDark = decoded['isDark'] == true;

      // Рюкзачок: только расходуемые предметы, которые есть в каталоге.
      final inv = <String, int>{};
      final rawInv = decoded['inventory'];
      if (rawInv is Map) {
        rawInv.forEach((k, v) {
          final item = k is String ? itemById(k) : null;
          if (item != null && !item.permanent && v is num && v > 0) {
            inv[k as String] = v.toInt();
          }
        });
      }
      inventory = inv;

      Set<String> readIds(String key, bool Function(String id) known) {
        final raw = decoded[key];
        if (raw is! List) return {};
        return raw.whereType<String>().where(known).toSet();
      }

      owned = readIds('owned', (id) => itemById(id)?.permanent ?? false);
      lessonsSolved = readIds('lessonsSolved', (id) => lessonById(id) != null);
      lessonsRetry = readIds('lessonsRetry', (id) => lessonById(id) != null)
        ..removeAll(lessonsSolved);
      lessonMistakes = readInt('lessonMistakes', 0);
      lessonGivenDay = readInt('lessonGivenDay', 1);
      rewardedToday = readInt('rewardedToday', 0);
      xpToday = readInt('xpToday', 0);
      final lb = decoded['lastBonusDate'];
      if (lb is String) lastBonusDate = lb;
      streak = readInt('streak', 0);
      final la = decoded['lastActionDate'];
      if (la is String) lastActionDate = la;
      interestTotal = readInt('interestTotal', 0);
      questsGuideSeen = decoded['questsGuideSeen'] == true;

      planBudget = readInt('planBudget', balance);
      plan = _basketsFromJson(decoded['plan']);
      fact = _basketsFromJson(decoded['fact']);
      planConfirmed = decoded['planConfirmed'] == true;

      final rawJournal = decoded['journal'];
      journal = rawJournal is List
          ? rawJournal
              .map(JournalEntry.fromJson)
              .whereType<JournalEntry>()
              .toList()
          : [];
      missionsDone = readIds('missionsDone', (id) => missionById(id) != null);
      saveDays = readInt('saveDays', 0);
      lastSaveDay = readInt('lastSaveDay', 0);
      final rawLog = decoded['savingsLog'];
      savingsLog = rawLog is List
          ? rawLog.whereType<num>().map((v) => math.max(0, v.toInt())).toList()
          : [];
      lastSummary = DaySummary.fromJson(decoded['lastSummary']);
      animationsOn = decoded['animationsOn'] != false;
      parentGiftDay = readInt('parentGiftDay', 0);
    } catch (_) {
      // Битый сейв — начинаем заново, но приложение живёт.
    }
  }

  /// Полный сброс (родительский режим → «Начать заново»).
  Future<void> reset() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_prefsKey);
    } catch (_) {}
    profile = null;
    pet = null;
    onboardingDone = false;
    isDark = false;
    justFinishedOnboarding = false;
    lastBonusDate = null;
    animationsOn = true;
    _resetProgress();
    journal = [];
    inventory = {};
    notifyListeners();
  }
}
