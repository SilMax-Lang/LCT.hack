import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:finny_pet/app.dart';
import 'package:finny_pet/data/lessons_data.dart';
import 'package:finny_pet/data/shop_data.dart';
import 'package:finny_pet/models/game_state.dart';
import 'package:finny_pet/models/pet.dart';
import 'package:finny_pet/screens/settings/settings_screen.dart';
import 'package:finny_pet/theme/kids_theme.dart';

import 'game_fixture.dart';

/// Вертикальный список открытой вкладки (в магазине есть ещё карусель
/// и лента отделов — они листаются вбок).
Finder _vertical() => find
    .byWidgetPredicate(
        (w) => w is Scrollable && w.axisDirection == AxisDirection.down)
    .first;

String _yesterday() => DateTime.now()
    .subtract(const Duration(days: 1))
    .toIso8601String()
    .substring(0, 10);

void main() {
  group('задания и опыт', () {
    test('класс = возраст − 6; финансы: 1–2 класс → 1, 3 → 2, 4 → 3', () {
      expect([7, 8, 9, 10].map((a) => recommendedGrade(a, LessonTrack.math)),
          [1, 2, 3, 4]);
      expect(
          [7, 8, 9, 10].map((a) => recommendedGrade(a, LessonTrack.finance)),
          [1, 1, 2, 3]);
    });

    test('награда 10/15/20/25, монеты не больше чем за 2 задания в день',
        () async {
      expect([1, 2, 3, 4].map(rewardForGrade), [10, 15, 20, 25]);

      final game = await readyGame();
      final lessons = lessonsOf(LessonTrack.math).take(4).toList();
      final r1 = game.answerLesson(lessons[0].id, lessons[0].correct);
      final r2 = game.answerLesson(lessons[1].id, lessons[1].correct);
      final r3 = game.answerLesson(lessons[2].id, lessons[2].correct);
      expect(r1.reward, lessons[0].reward);
      expect(r2.reward, lessons[1].reward);
      expect(r3.reward, 0);
      expect(r3.dailyLimitReached, isTrue);
      expect(game.lessonsSolved, contains(lessons[2].id),
          reason: 'задание решено, просто без монет');

      game.nextDay();
      final r4 = game.answerLesson(lessons[3].id, lessons[3].correct);
      expect(r4.reward, lessons[3].reward, reason: 'новый день — снова монеты');
    });

    test('опыт: задание 5, конец дня 10, не больше 25 за день', () async {
      final game = await readyGame();
      for (final l in lessonsCatalog.take(6)) {
        game.answerLesson(l.id, l.correct);
      }
      expect(game.pet!.xp, 25, reason: '6 заданий × 5 = 30, но потолок 25');

      game.nextDay();
      expect(game.pet!.xp, 25, reason: 'опыт за день упёрся в потолок');

      game.nextDay();
      expect(game.pet!.xp, 29,
          reason: 'новый день: сыт и чист (+1 +3), без плана и копилки');
    });

    test('предметы и копилка опыта не дают', () async {
      final game = await readyGame();
      game.useItem('milk');
      game.deposit(10);
      expect(game.pet!.xp, 0);
    });

    test('этапы: Малыш, Ученик, Исследователь', () {
      expect(Pet.stageForLevel(1), startsWith('Малыш'));
      expect(Pet.stageForLevel(teenLevel), startsWith('Ученик'));
      expect(Pet.stageForLevel(adultLevel), startsWith('Исследователь'));
    });
  });

  group('экономика', () {
    test('огонёк: +10 за 3 дня, +20 за 7, дальше +10 каждые 7', () async {
      expect(streakBonusFor(3), 10);
      expect(streakBonusFor(7), 20);
      expect(streakBonusFor(14), 10);
      expect(streakBonusFor(5), 0);

      final game = await readyGame();
      game.streak = 2;
      game.lastActionDate = _yesterday();
      game.missionsDone.add('m_first_save'); // практику считаем отдельно
      final before = game.balance;
      game.deposit(10);
      expect(game.streak, 3);
      expect(game.balance, before - 10 + 10, reason: '+10 за 3 дня подряд');
      expect(game.pendingBonusText, contains('3 дн.'));
    });

    test('вклад: 20 % раз в 5 дней, не больше 500 за раз', () async {
      final game = await readyGame();
      game.balance = 100;
      game.deposit(100);
      for (var i = 0; i < 3; i++) {
        expect(game.nextDay().interest, 0);
      }
      final summary = game.nextDay(); // день 5 — конец игрового года
      expect(summary.interest, 20);
      expect(game.savings, 120);

      game.savings = 10000;
      for (var i = 0; i < daysPerYear; i++) {
        game.nextDay();
      }
      expect(game.savings, 10000 + interestCap);
    });

    test('курсы по порядку, при голоде игрушки и обучение закрыты', () async {
      final game = await readyGame();
      game.balance = 1000;
      expect(game.buyItem('course_saver'), BuyResult.locked);
      expect(game.buyItem('course_abc'), BuyResult.ok);
      expect(game.buyItem('course_abc'), BuyResult.owned);

      game.pet!.hunger = hungryBlockAt;
      expect(game.buyItem('ball'), BuyResult.hungry);
      expect(game.buyItem('course_saver'), BuyResult.hungry);
      expect(game.buyItem('apple'), BuyResult.ok, reason: 'еду купить можно');
    });

    test('вещи для дома и украшения — навсегда, украшение продаётся за 70 %',
        () async {
      final game = await readyGame();
      game.balance = 500;
      expect(game.buyItem('bowl'), BuyResult.ok);
      expect(game.owned, contains('bowl'));
      expect(game.inventory.containsKey('bowl'), isFalse);

      final crown = itemById('decor_crown')!;
      game.buyItem(crown.id);
      final before = game.balance;
      expect(game.sellDecoration(crown.id), isTrue);
      expect(game.balance, before + 70);
      expect(game.owned, isNot(contains(crown.id)));
      expect(game.sellDecoration('bowl'), isFalse, reason: 'миску не продать');
    });

    test('каталог: 20 украшений 10/6/4, цены по документу', () {
      final byRarity = {
        for (final r in Rarity.values)
          r: decorations.where((d) => d.rarity == r).toList(),
      };
      expect(decorations.length, 20);
      expect(byRarity[Rarity.common]!.length, 10);
      expect(byRarity[Rarity.rare]!.length, 6);
      expect(byRarity[Rarity.epic]!.length, 4);
      expect(itemById('apple')!.price, 5);
      expect(itemById('ball')!.price, 15);
      expect(itemById('teddy')!.price, 30);
      for (final id in ['bowl', 'drinker', 'bed']) {
        expect(itemById(id)!.mandatory, isTrue);
        expect(itemById(id)!.permanent, isTrue);
      }
    });
  });

  group('план бюджета', () {
    test('шаги 5/10 в пределах бюджета, после подтверждения — только факт',
        () async {
      final game = await readyGame();
      final budget = game.planBudget;
      game.changePlan(BudgetBasket.mandatory, planStepBig);
      game.changePlan(BudgetBasket.savings, planStepSmall);
      expect(game.planned, 15);
      expect(game.unplanned, budget - 15);

      // Больше бюджета не распределить.
      for (var i = 0; i < 100; i++) {
        game.changePlan(BudgetBasket.optional, planStepBig);
      }
      expect(game.planned, budget);

      game.confirmPlan();
      expect(game.changePlan(BudgetBasket.mandatory, planStepSmall), isFalse);

      game.buyItem('apple');
      game.deposit(10);
      expect(game.fact[BudgetBasket.mandatory], 5);
      expect(game.fact[BudgetBasket.savings], 10);

      game.nextDay();
      expect(game.planConfirmed, isFalse, reason: 'новый день — новый план');
      expect(game.planned, 0);
    });
  });

  testWidgets('покупка — через окно «Купить / Отменить»', (tester) async {
    await narrow(tester);
    final game = await readyGame();
    await tester.pumpWidget(FinnyApp(gameState: game));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Магазин'));
    await tester.pumpAndSettle();

    await tester.scrollUntilVisible(find.text('Молочко × 1'), 200,
        scrollable: _vertical());
    await tester.pumpAndSettle();
    final milkButton = find.descendant(
      of: find.ancestor(
          of: find.text('Молочко × 1'), matching: find.byType(Card)),
      matching: find.byType(ElevatedButton),
    );
    await tester.ensureVisible(milkButton);
    await tester.pumpAndSettle();
    game.missionsDone.add('m_need_first'); // без награды за практику
    final before = game.balance;

    await tester.tap(milkButton);
    await tester.pumpAndSettle();
    expect(find.text('Купить'), findsOneWidget);
    await tester.tap(find.text('Отменить'));
    await tester.pumpAndSettle();
    expect(game.balance, before, reason: 'отмена — ничего не списали');

    await tester.tap(milkButton);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Купить'));
    await tester.pumpAndSettle();
    expect(game.balance, before - 10);
    expect(find.text('Молочко × 2'), findsOneWidget);
    await tester.pump(const Duration(seconds: 1));
  });

  testWidgets('план бюджета на 360dp: распределить, подтвердить, план/факт',
      (tester) async {
    await narrow(tester);
    final game = await readyGame();
    await tester.pumpWidget(FinnyApp(gameState: game));
    await tester.pumpAndSettle();
    await tester.tap(find.text('План'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('+10').first);
    await tester.pumpAndSettle();
    expect(game.plan[BudgetBasket.mandatory], 10);

    await tester.scrollUntilVisible(find.text('Подтвердить план'), 200,
        scrollable: _vertical());
    await tester.drag(_vertical(), const Offset(0, -300));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить план'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(game.planConfirmed, isTrue);
    expect(find.textContaining('план 10 • факт 0'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pump(const Duration(seconds: 1));
  });

  testWidgets('скрытый вход: 7 нажатий на версию', (tester) async {
    await narrow(tester);
    final game = await readyGame();
    await tester.pumpWidget(GameStateScope(
      notifier: game,
      child: MaterialApp(
        theme: KidsTheme.light(),
        home: const SettingsScreen(),
      ),
    ));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text(SettingsScreen.version), 200,
        scrollable: find.byType(Scrollable).first);
    await tester.pumpAndSettle();

    for (var i = 0; i < 6; i++) {
      await tester.tap(find.text(SettingsScreen.version));
    }
    await tester.pumpAndSettle();
    expect(find.text('🧪 Режим эксперта'), findsNothing);

    await tester.tap(find.text(SettingsScreen.version));
    await tester.pumpAndSettle();
    expect(find.text('🧪 Режим эксперта'), findsOneWidget);

    await tester.tap(find.text('+10 XP'));
    await tester.pumpAndSettle();
    expect(game.pet!.xp, 10);
  });
}
