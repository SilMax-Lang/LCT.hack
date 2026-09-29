import 'package:flutter/material.dart';

import '../../app.dart';
import '../../data/lessons_data.dart';
import '../../data/missions_data.dart';
import '../../models/game_state.dart';
import '../../theme/kids_theme.dart';
import '../../widgets/day_paper.dart';

/// Дневник (ТЗ 2.5.11): итоги прошлого дня, история монеток за сегодня,
/// прогресс цели и роста, решённые задания и практика.
class DiaryScreen extends StatelessWidget {
  const DiaryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final game = GameStateScope.of(context);
    final pet = game.pet;
    final last = game.lastSummary;
    final today = game.todayJournal;
    final solved =
        lessonsCatalog.where((l) => game.lessonsSolved.contains(l.id)).toList();

    return Scaffold(
      appBar: AppBar(title: const Text('📖 Дневник')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _Section(
            title: last == null
                ? '📅 Итоги прошлого дня'
                : '📅 Итоги дня ${last.day - 1}',
            children: last == null
                ? const [Text('Первый день ещё идёт. Итоги будут завтра.')]
                : [
                    DayChecks(summary: last),
                    const SizedBox(height: 6),
                    Text('💡 ${last.advice}',
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                  ],
          ),
          _Section(
            title: '🧾 Сегодня, день ${game.day}',
            children: today.isEmpty
                ? const [Text('Пока ничего не покупали и не откладывали.')]
                : [for (final e in today) _EntryRow(entry: e)],
          ),
          _Section(
            title: '🎯 Цель: ${game.goalName}',
            children: [
              Text('Накоплено ${game.savings} из ${game.goalTarget} • '
                  'осталось ${game.goalLeft}'),
              const SizedBox(height: 6),
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: LinearProgressIndicator(
                    value: game.goalProgress, minHeight: 12),
              ),
            ],
          ),
          if (pet != null)
            _Section(
              title: '🌱 Рост питомца',
              children: [
                Text('${pet.name}: ${pet.stage}, уровень ${pet.level}, '
                    'опыт ${pet.xp}/100'),
                const SizedBox(height: 4),
                Text(
                  'Опыт в конце дня: +1 и ещё по +3 за каждое — питомец сыт '
                  'и чист, план выполнен, монетки отложены. За задание — '
                  '+$lessonXp.',
                  style: TextStyle(color: KidsTheme.muted(context)),
                ),
              ],
            ),
          _Section(
            title: '🧩 Практика: ${game.missionsDone.length} из '
                '${missionsCatalog.length}',
            children: [
              for (final m in missionsCatalog)
                Text(
                  '${game.missionsDone.contains(m.id) ? '✅' : '🔹'} '
                  '${m.emoji} ${m.title}',
                ),
            ],
          ),
          _Section(
            title: '⭐ Решённые задания: ${solved.length} из '
                '${lessonsCatalog.length}',
            children: solved.isEmpty
                ? const [Text('Реши первое задание на вкладке «Задания».')]
                : [
                    for (final l in solved)
                      Text('✅ ${l.emoji} ${l.title} • ${l.topic.title}'),
                  ],
          ),
        ],
      ),
    );
  }
}

class _EntryRow extends StatelessWidget {
  final JournalEntry entry;

  const _EntryRow({required this.entry});

  @override
  Widget build(BuildContext context) {
    final parts = <String>[
      if (entry.coins != 0)
        '${entry.coins > 0 ? '+' : '−'}${entry.coins.abs()} 🪙',
      if (entry.savings != 0)
        '${entry.savings > 0 ? '+' : '−'}${entry.savings.abs()} 🐷',
    ];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Text(entry.emoji, style: const TextStyle(fontSize: 20)),
          const SizedBox(width: 8),
          Expanded(child: Text(entry.text)),
          Text(parts.join('  '),
              style: const TextStyle(fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  final List<Widget> children;

  const _Section({required this.title, required this.children});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title,
                style:
                    const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 8),
            ...children,
          ],
        ),
      ),
    );
  }
}
