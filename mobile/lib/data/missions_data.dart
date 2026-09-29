import 'lessons_data.dart';

/// Практика — задания-действия в самой игре (ТЗ 2.5.8: игровая ситуация
/// с выбором и последствиями, а не только выбор ответа). Ребёнок делает
/// настоящее действие — составляет план, откладывает, покупает, —
/// а игра засчитывает его и объясняет, почему это разумно.
///
/// Как засчитывается каждое — в `GameState` (метод `_completeMission`).
/// Новая практика = строка здесь + одна проверка там.
class Mission {
  final String id;
  final FinTopic topic;
  final String emoji;
  final String title;

  /// Что сделать — одной фразой.
  final String task;

  /// Где это сделать.
  final String where;

  /// Объяснение после выполнения: почему это разумно.
  final String lesson;

  const Mission({
    required this.id,
    required this.topic,
    required this.emoji,
    required this.title,
    required this.task,
    required this.where,
    required this.lesson,
  });
}

/// Награда за практику — одна на всех.
const int missionReward = 10;

/// Сколько разных дней надо откладывать для «Копим регулярно».
const int missionSaveDays = 3;

const List<Mission> missionsCatalog = [
  Mission(
    id: 'm_plan',
    topic: FinTopic.budget,
    emoji: '📋',
    title: 'Составь план',
    task: 'Разложи монетки на «надо», «хочу» и копилку и подтверди план.',
    where: 'Вкладка «План»',
    lesson: 'План заранее решает, сколько потратить и сколько отложить — '
        'так монет хватает на важное.',
  ),
  Mission(
    id: 'm_plan_kept',
    topic: FinTopic.budget,
    emoji: '🎯',
    title: 'Уложись в план',
    task: 'Потрать на «хочу» не больше плана, а отложи не меньше — '
        'и начни новый день.',
    where: 'Вкладки «План» и «Питомец»',
    lesson: 'Когда факт совпадает с планом, ты управляешь монетками, '
        'а не они тобой.',
  ),
  Mission(
    id: 'm_first_save',
    topic: FinTopic.savings,
    emoji: '🐷',
    title: 'Первая монетка',
    task: 'Положи монетки в копилку.',
    where: 'Вкладка «Банк»',
    lesson: 'Даже маленькие суммы складываются в большую цель.',
  ),
  Mission(
    id: 'm_save_3',
    topic: FinTopic.savings,
    emoji: '📆',
    title: 'Копим регулярно',
    task: 'Откладывай в копилку $missionSaveDays разных дня.',
    where: 'Вкладка «Банк»',
    lesson: 'Регулярность важнее размера: понемногу, но часто — '
        'и цель ближе с каждым днём.',
  ),
  Mission(
    id: 'm_need_first',
    topic: FinTopic.purchases,
    emoji: '🍎',
    title: 'Сначала надо',
    task: 'Купи питомцу еду, уход, лекарство или вещь для дома.',
    where: 'Вкладка «Магазин», отделы «Надо»',
    lesson: 'Обязательные расходы — в первую очередь: от них зависит, '
        'сыт и здоров ли питомец.',
  ),
  Mission(
    id: 'm_deal',
    topic: FinTopic.purchases,
    emoji: '🏷️',
    title: 'Покупка со скидкой',
    task: 'Купи товар дня со скидкой.',
    where: 'Вкладка «Магазин», сверху',
    lesson: 'Скидка помогает заплатить меньше. Но покупать стоит, только '
        'если вещь правда нужна.',
  ),
];

Mission? missionById(String id) {
  for (final m in missionsCatalog) {
    if (m.id == id) return m;
  }
  return null;
}
