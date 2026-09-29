import 'package:flutter/material.dart';

import '../../app.dart';
import '../../data/lessons_data.dart';
import '../../data/missions_data.dart';
import '../../models/game_state.dart';
import '../../models/player_profile.dart';
import '../../theme/kids_theme.dart';

/// Родительский режим: прогресс ребёнка на дорогах, возраст
/// (от него зависят рекомендованные задания) и сбросы.
/// Открывается из настроек только после решения «взрослых» примеров.
class ParentScreen extends StatelessWidget {
  const ParentScreen({super.key});

  Future<void> _editAge(BuildContext context) async {
    final game = GameStateScope.read(context);
    final current = game.age;
    final picked = await showDialog<int>(
      context: context,
      builder: (dialogContext) => SimpleDialog(
        title: const Text('👦 Возраст ребёнка'),
        children: PlayerProfile.ageChoices
            .map(
              (age) => SimpleDialogOption(
                onPressed: () => Navigator.of(dialogContext).pop(age),
                // Галочка иконкой, а не символом «✓»: его нет в Roboto.
                child: Row(
                  children: [
                    SizedBox(
                      width: 24,
                      child: age == current
                          ? const Icon(Icons.check, size: 18)
                          : null,
                    ),
                    Text(PlayerProfile.labelFor(age),
                        style: const TextStyle(fontSize: 18)),
                  ],
                ),
              ),
            )
            .toList(),
      ),
    );
    if (picked != null) game.updateAge(picked);
  }

  Future<bool> _confirm(
      BuildContext context, String title, String text, String yes) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(title),
        content: Text(text),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text(yes),
          ),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _resetLessons(BuildContext context) async {
    final game = GameStateScope.read(context);
    final ok = await _confirm(
      context,
      'Сбросить задания?',
      'Дороги «Математика» и «Финансы» начнутся заново. Монетки, питомец '
          'и копилка останутся.',
      'Сбросить',
    );
    if (ok) game.resetLessons();
  }

  Future<void> _resetAll(BuildContext context) async {
    final game = GameStateScope.read(context);
    final navigator = Navigator.of(context);
    final ok = await _confirm(
      context,
      'Начать игру заново?',
      'Питомец, монетки и весь прогресс будут удалены.',
      'Удалить всё',
    );
    if (ok) {
      await game.reset();
      // Приложение само переключится на онбординг, стек чистим.
      navigator.popUntil((route) => route.isFirst);
    }
  }

  @override
  Widget build(BuildContext context) {
    final game = GameStateScope.of(context);
    final scheme = Theme.of(context).colorScheme;
    final age = game.age;

    return Scaffold(
      appBar: AppBar(title: const Text('👨‍👩‍👧 Родительский режим')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '📈 Прогресс: ${game.nickname}',
                    style: const TextStyle(
                        fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 12),
                  for (final track in LessonTrack.values) ...[
                    _TrackProgress(
                      track: track,
                      solved: game.solvedOn(track),
                      total: lessonsOf(track).length,
                      recommended: recommendedGrade(age, track),
                    ),
                    const SizedBox(height: 12),
                  ],
                  // Без оценок и счётчика ошибок (ТЗ 2.5.12): только
                  // что пройдено и что ждёт повторения.
                  Text(
                    '🧩 Практика в игре: ${game.missionsDone.length} '
                    'из ${missionsCatalog.length}\n'
                    '🔁 Ждут повторения: ${game.lessonsRetry.length}\n'
                    '🐷 В копилке: ${game.savings} из ${game.goalTarget} '
                    '(${game.goalName})\n'
                    '🌱 Питомец: ${game.pet?.stage ?? '—'}, '
                    'уровень ${game.pet?.level ?? 1}\n'
                    '📅 Игровой день: ${game.day}',
                    style: const TextStyle(height: 1.5),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '📚 Пройденные темы',
                    style:
                        TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  for (final topic in FinTopic.values)
                    _TopicRow(
                      topic: topic,
                      solved: lessonsCatalog
                          .where((l) =>
                              l.topic == topic &&
                              game.lessonsSolved.contains(l.id))
                          .length,
                      total: lessonsCatalog
                          .where((l) => l.topic == topic)
                          .length,
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          const _GoalsCard(),
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              leading: const Text('🎁', style: TextStyle(fontSize: 24)),
              title: const Text('Подарить +$parentGift 🪙'),
              subtitle: Text(game.parentGiftAvailable
                  ? 'Раз в игровой день — за помощь дома или хорошую идею. '
                      'Ребёнок увидит «Подарок от взрослого»'
                  : 'Сегодня уже подарено. Завтра — снова можно'),
              enabled: game.parentGiftAvailable,
              onTap: game.giveParentGift,
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Text('👦', style: TextStyle(fontSize: 24)),
                  title: Text(age == null
                      ? 'Возраст не указан'
                      : 'Возраст: ${PlayerProfile.labelFor(age)}'),
                  subtitle: const Text(
                      'По возрасту подбираются рекомендованные задания'),
                  trailing: const Icon(Icons.edit),
                  onTap: () => _editAge(context),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Text('🧹', style: TextStyle(fontSize: 24)),
                  title: const Text('Сбросить задания'),
                  subtitle: const Text('Пройти дороги с начала'),
                  onTap: () => _resetLessons(context),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Text('🔄', style: TextStyle(fontSize: 24)),
                  title: const Text('Начать игру заново'),
                  subtitle: const Text('Стереть питомца и монетки'),
                  onTap: () => _resetAll(context),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: KidsTheme.soft(context),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Text(
              '💡 Все задания открыты. Возраст лишь подсказывает ребёнку, '
              'с чего начать: класс = возраст − 6 (7 лет — 1 класс, 10+ — 4). '
              'В «Финансах» 1–2 класс — 1 уровень, 3 — 2-й, 4 — 3-й. '
              'Ошибка не отнимает монет: задание просто просит повторить.\n\n'
              '🗑️ «Начать игру заново» удаляет все данные игры с этого '
              'устройства. Другие данные приложение не хранит.',
              style: TextStyle(height: 1.4, color: scheme.onSurface),
            ),
          ),
        ],
      ),
    );
  }
}

class _TopicRow extends StatelessWidget {
  final FinTopic topic;
  final int solved;
  final int total;

  const _TopicRow({
    required this.topic,
    required this.solved,
    required this.total,
  });

  @override
  Widget build(BuildContext context) {
    // Эмодзи, а не типографские ▶/⬜: их нет в Roboto (см. glyphs_test).
    final mark = total > 0 && solved == total
        ? '✅'
        : (solved > 0 ? '📖' : '🔹');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Text('$mark ${topic.emoji} ${topic.title}: $solved из $total'),
    );
  }
}

/// Цели приложения — из Единой рамки компетенций (ТЗ 1, 2.5.12).
class _GoalsCard extends StatelessWidget {
  const _GoalsCard();

  static const _goals = [
    'Понимать, зачем нужен бюджет и что расходы не должны быть больше '
        'доходов',
    'Отличать обязательные расходы от желаний («надо» и «хочу»)',
    'Планировать покупки, когда монет мало',
    'Ставить цель и регулярно откладывать часть монет',
    'Оценивать свои решения: сравнивать план и факт',
  ];

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '🎯 Чему учит игра',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            for (final g in _goals)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Text('• $g'),
              ),
            const SizedBox(height: 6),
            Text(
              'Монетки игровые. Нет рекламы, покупок и сбора данных — '
              'всё хранится только на этом устройстве.',
              style: TextStyle(color: KidsTheme.muted(context)),
            ),
          ],
        ),
      ),
    );
  }
}

class _TrackProgress extends StatelessWidget {
  final LessonTrack track;
  final int solved;
  final int total;
  final int recommended;

  const _TrackProgress({
    required this.track,
    required this.solved,
    required this.total,
    required this.recommended,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${track.emoji} ${track.title}: $solved из $total '
          '• рекомендован ${track.gradeLabel(recommended)}',
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: LinearProgressIndicator(
            value: total == 0 ? 0 : solved / total,
            minHeight: 12,
            color: track.color,
          ),
        ),
      ],
    );
  }
}
