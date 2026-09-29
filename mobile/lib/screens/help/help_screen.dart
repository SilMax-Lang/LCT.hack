import 'package:flutter/material.dart';

import '../../data/glossary_data.dart';
import '../../theme/kids_theme.dart';

/// «Как играть» и словарик — открываются в любой момент: с главной
/// и из настроек (ТЗ 2.5.1 — вернуться к подсказке, 2.5.11 — справочный
/// раздел с терминами).
class HelpScreen extends StatelessWidget {
  const HelpScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('❓ Как играть')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
            'Каждый день у тебя есть монетки. С ними можно сделать три вещи:',
            style: TextStyle(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 10),
          const _Rule(
            emoji: '🍎',
            title: 'Потратить на «надо»',
            text: 'Еда, уход и лекарства. Без них питомцу плохо — '
                'покупай в первую очередь.',
          ),
          const _Rule(
            emoji: '🧸',
            title: 'Потратить на «хочу»',
            text: 'Игрушки и украшения. Радуют питомца, но могут подождать.',
          ),
          const _Rule(
            emoji: '🐷',
            title: 'Отложить в копилку',
            text: 'Монетки на цель. Понемногу каждый день — и цель ближе.',
          ),
          const SizedBox(height: 8),
          const _Rule(
            emoji: '📋',
            title: 'Как расти быстрее',
            text: 'Составь план, уложись в него, отложи в копилку и '
                'позаботься о питомце. Каждое из этого даёт опыт в конце дня.',
          ),
          const _Rule(
            emoji: '🔁',
            title: 'Ошибся — не страшно',
            text: 'Ошибка ничего не отнимает. Задание можно повторить, '
                'а план — поменять завтра.',
          ),
          const SizedBox(height: 16),
          const Text(
            '📖 Словарик',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          for (final term in glossary)
            Card(
              child: ListTile(
                leading:
                    Text(term.emoji, style: const TextStyle(fontSize: 26)),
                title: Text(
                  term.word,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                subtitle: Text(
                  term.meaning,
                  style: TextStyle(color: KidsTheme.muted(context)),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _Rule extends StatelessWidget {
  final String emoji;
  final String title;
  final String text;

  const _Rule({required this.emoji, required this.title, required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: KidsTheme.soft(context),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(emoji, style: const TextStyle(fontSize: 28)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(fontWeight: FontWeight.bold)),
                Text(text),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
