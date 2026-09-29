import 'package:flutter/material.dart';

import '../../app.dart';
import '../../data/shop_data.dart';
import '../../models/game_state.dart';
import '../../theme/kids_theme.dart';
import '../../widgets/action_spark.dart';
import '../../widgets/kids_button.dart';

/// План бюджета на день: монеты начала дня раскладываются по четырём
/// корзинам — «Надо», «Хочу», «Обучение», «Копилка» — шагами по 5 и 10.
///
/// План можно менять только до подтверждения (правило ТЗ). После — только
/// сравнение «план / факт»: сколько на самом деле ушло в каждую корзину.
/// Новый день — новый план.
class PlanScreen extends StatefulWidget {
  const PlanScreen({super.key});

  @override
  State<PlanScreen> createState() => _PlanScreenState();
}

class _PlanScreenState extends State<PlanScreen> {
  int _spark = 0;

  Future<void> _confirm(GameState game) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Подтвердить план?'),
        content: Text(
          'После подтверждения план на этот день не меняется — '
          'будем сравнивать его с тем, что получится на самом деле.'
          '${game.unplanned > 0 ? '\nНе распределено: ${game.unplanned} 🪙.' : ''}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Ещё подумаю'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Подтвердить'),
          ),
        ],
      ),
    );
    if (ok == true && mounted) {
      game.confirmPlan();
      setState(() => _spark++);
    }
  }

  @override
  Widget build(BuildContext context) {
    final game = GameStateScope.of(context);
    final confirmed = game.planConfirmed;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          confirmed
              ? 'План на день ${game.day}: план и факт'
              : 'План на день ${game.day}',
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 4),
        Text(
          confirmed
              ? 'План подтверждён. Смотри, как получается на самом деле.'
              : 'Разложи ${game.planBudget} 🪙 по корзинам. '
                  'Сначала — «Надо».',
          style: TextStyle(color: KidsTheme.muted(context)),
        ),
        const SizedBox(height: 12),
        for (final basket in BudgetBasket.values) ...[
          confirmed
              ? _FactCard(
                  basket: basket,
                  planned: game.plan[basket] ?? 0,
                  actual: game.fact[basket] ?? 0,
                )
              : _PlanCard(
                  basket: basket,
                  value: game.plan[basket] ?? 0,
                  canAdd: game.unplanned > 0,
                  onChange: (d) => game.changePlan(basket, d),
                ),
          const SizedBox(height: 10),
        ],
        if (!confirmed) ...[
          _Unplanned(amount: game.unplanned),
          const SizedBox(height: 12),
          SparkOnAction(
            trigger: _spark,
            spread: 48,
            child: KidsButton(
              text: 'Подтвердить план',
              icon: Icons.check_circle_outline,
              onPressed: game.planned == 0 ? null : () => _confirm(game),
            ),
          ),
        ] else
          SparkOnAction(
            trigger: _spark,
            spread: 48,
            child: _Summary(game: game),
          ),
      ],
    );
  }
}

class _PlanCard extends StatelessWidget {
  final BudgetBasket basket;
  final int value;
  final bool canAdd;
  final ValueChanged<int> onChange;

  const _PlanCard({
    required this.basket,
    required this.value,
    required this.canAdd,
    required this.onChange,
  });

  @override
  Widget build(BuildContext context) {
    Widget step(int delta) {
      final enabled = delta > 0 ? canAdd : value > 0;
      return Expanded(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 3),
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(48, 48),
              padding: EdgeInsets.zero,
              foregroundColor: basket.color,
            ),
            onPressed: enabled ? () => onChange(delta) : null,
            // Минус — настоящий «−» (U+2212), он есть в Roboto.
            child: Text(delta > 0 ? '+$delta' : '−${-delta}'),
          ),
        ),
      );
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          children: [
            Row(
              children: [
                Text(basket.emoji, style: const TextStyle(fontSize: 26)),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    basket.title,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                Text(
                  '$value 🪙',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    color: basket.color,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                step(-planStepBig),
                step(-planStepSmall),
                step(planStepSmall),
                step(planStepBig),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Unplanned extends StatelessWidget {
  final int amount;

  const _Unplanned({required this.amount});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: KidsTheme.soft(context),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Text(
        amount > 0
            ? 'У тебя осталось $amount монеток. '
                'Может, добавим их в копилку на мечту? 🐷'
            : 'Все монетки распределены — отлично! ✅',
        style: const TextStyle(fontWeight: FontWeight.w600),
      ),
    );
  }
}

/// План и факт по корзине: полоска факта относительно плана и перерасход
/// словами (а не только цветом).
class _FactCard extends StatelessWidget {
  final BudgetBasket basket;
  final int planned;
  final int actual;

  const _FactCard({
    required this.basket,
    required this.planned,
    required this.actual,
  });

  @override
  Widget build(BuildContext context) {
    final over = actual - planned;
    final progress = planned == 0 ? (actual > 0 ? 1.0 : 0.0) : actual / planned;
    final String note;
    if (basket == BudgetBasket.savings) {
      note = actual >= planned
          ? 'план выполнен ✅'
          : 'отложи ещё ${planned - actual}';
    } else if (over > 0) {
      note = 'перерасход +$over ⚠️';
    } else {
      note = 'в пределах плана ✅';
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(basket.emoji, style: const TextStyle(fontSize: 26)),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    basket.title,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                Text(
                  'план $planned • факт $actual',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ],
            ),
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: LinearProgressIndicator(
                value: progress.clamp(0.0, 1.0),
                minHeight: 12,
                color: over > 0 && basket != BudgetBasket.savings
                    ? const Color(0xFFD84315)
                    : basket.color,
              ),
            ),
            const SizedBox(height: 4),
            Text(note, style: TextStyle(color: KidsTheme.muted(context))),
          ],
        ),
      ),
    );
  }
}

class _Summary extends StatelessWidget {
  final GameState game;

  const _Summary({required this.game});

  @override
  Widget build(BuildContext context) {
    final spent = BudgetBasket.values
        .where((b) => b != BudgetBasket.savings)
        .fold<int>(0, (a, b) => a + (game.fact[b] ?? 0));
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: KidsTheme.soft(context),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Text(
        'Потрачено $spent 🪙, отложено ${game.fact[BudgetBasket.savings] ?? 0} 🪙.\n'
        'Новый план — на следующий день.',
        style: const TextStyle(fontWeight: FontWeight.w600, height: 1.35),
      ),
    );
  }
}
