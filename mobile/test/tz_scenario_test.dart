import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:finny_pet/app.dart';
import 'package:finny_pet/data/glossary_data.dart';
import 'package:finny_pet/data/lessons_data.dart';
import 'package:finny_pet/data/missions_data.dart';
import 'package:finny_pet/data/shop_data.dart';
import 'package:finny_pet/models/game_state.dart';
import 'package:finny_pet/models/pet.dart';

import 'game_fixture.dart';

/// Проверки по пунктам ТЗ, которых не было в других тестах:
/// история периода, нехватка монет, рост от решений, срок цели,
/// практика, демо-профиль, сохранение. Номера пунктов — в названиях.
void main() {
  group('2.5.4 / 2.5.6 история монеток', () {
    test('покупка, копилка и доход записаны с суммой и источником', () async {
      final game = await readyGame();
      final start = game.todayJournal;
      expect(start.single.text, 'Стартовый бюджет');
      expect(start.single.coins, game.balance);

      game.missionsDone.addAll(missionsCatalog.map((m) => m.id));
      game.buyItem('apple');
      game.deposit(10);
      final today = game.todayJournal;
      expect(today[0].text, 'В копилку');
      expect(today[0].coins, -10);
      expect(today[0].savings, 10);
      expect(today[1].text, contains('Яблочко'));
      expect(today[1].coins, -itemById('apple')!.price);

      game.nextDay();
      final income = game.todayJournal.last;
      expect(income.text, 'Доход за день');
      expect(income.coins, startIncome);
    });

    test('каждое изменение кошелька объяснено записью', () async {
      final game = await readyGame();
      final lessons = lessonsOf(LessonTrack.finance).take(2).toList();
      for (final l in lessons) {
        game.answerLesson(l.id, l.correct);
      }
      game.buyItem('apple');
      game.deposit(20);
      game.withdraw(5);
      game.nextDay();
      final coins = game.journal.fold<int>(0, (a, e) => a + e.coins);
      expect(coins, game.balance, reason: 'сумма записей = кошелёк');
      final saved = game.journal.fold<int>(0, (a, e) => a + e.savings);
      expect(saved, game.savings, reason: 'сумма записей = копилка');
    });
  });

  group('2.5.6 нехватка монет', () {
    test('в минус уйти нельзя', () async {
      final game = await readyGame();
      game.balance = 3;
      expect(game.buyItem('teddy'), BuyResult.noMoney);
      expect(game.deposit(10), isFalse);
      expect(game.withdraw(1), isFalse);
      expect(game.balance, 3);
    });

    testWidgets('нажали на дорогой товар — объяснение и варианты',
        (tester) async {
      await narrow(tester);
      final game = await readyGame();
      game.balance = 3;
      await tester.pumpWidget(FinnyApp(gameState: game));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Магазин'));
      await tester.pumpAndSettle();

      final teddy = find.text('Плюшевый мишка');
      await tester.scrollUntilVisible(teddy, 200,
          scrollable: find
              .byWidgetPredicate((w) =>
                  w is Scrollable && w.axisDirection == AxisDirection.down)
              .first);
      await tester.pumpAndSettle();
      final button = find.descendant(
        of: find.ancestor(of: teddy, matching: find.byType(Card)),
        matching: find.byType(ElevatedButton),
      );
      await tester.ensureVisible(button);
      await tester.pumpAndSettle();
      await tester.tap(button);
      await tester.pumpAndSettle();

      expect(find.textContaining('Не хватает 27 🪙'), findsWidgets);
      expect(find.textContaining('Дождаться нового дня'), findsOneWidget);
      await tester.tap(find.text('Понятно'));
      await tester.pumpAndSettle();
      expect(game.balance, 3);
    });
  });

  group('2.5.10 рост от решений за день', () {
    test('план выполнен, копилка, питомец сыт — максимум опыта', () async {
      final game = await readyGame();
      game.changePlan(BudgetBasket.mandatory, 10);
      game.changePlan(BudgetBasket.optional, 10);
      game.changePlan(BudgetBasket.savings, 10);
      game.confirmPlan();
      game.buyItem('apple');
      game.deposit(10);
      final xpBefore = game.pet!.xp;
      final summary = game.nextDay();
      expect(summary.needsMet && summary.planKept && summary.saved, isTrue);
      expect(summary.growthXp, endOfDayXp);
      expect(game.pet!.xp, xpBefore + endOfDayXp);
      expect(summary.advice, contains('Отличный день'));
    });

    test('голоден, без плана и копилки — 1 опыт и совет, что исправить',
        () async {
      final game = await readyGame();
      game.pet!.hunger = 20;
      final summary = game.nextDay();
      expect(summary.needsMet, isFalse);
      expect(summary.growthXp, 1);
      expect(summary.advice, contains('еду'));
      expect(game.pet!.level, 1, reason: 'прогресс не обнуляется');
    });

    test('потратили на «хочу» больше плана — план не выполнен', () async {
      final game = await readyGame();
      game.changePlan(BudgetBasket.mandatory, 10);
      game.confirmPlan();
      game.buyItem('ball');
      final summary = game.nextDay();
      expect(summary.planConfirmed, isTrue);
      expect(summary.planKept, isFalse);
      expect(summary.advice, contains('«хочу»'));
    });

    test('у эмоции есть объяснение причины', () async {
      final pet = (await readyGame()).pet!;
      pet.hunger = 30;
      expect(pet.moodReason, contains('Сытость 30'));
      pet.hunger = 100;
      pet.happiness = 10;
      expect(pet.moodReason, contains('Счастье 10'));
    });
  });

  group('2.5.7 срок цели по среднему пополнению', () {
    test('пока не копили — срока нет; потом — по средней сумме', () async {
      final game = await readyGame();
      expect(game.avgDeposit, 0);
      expect(game.daysToGoal(100), isNull);

      game.balance = 500;
      game.deposit(10);
      game.nextDay();
      game.deposit(30);
      expect(game.avgDeposit, 20, reason: '(10 + 30) / 2');
      expect(game.daysToGoal(100), 5);
      expect(game.daysToGoal(0), 0);
    });
  });

  group('2.5.8 практика в игре', () {
    test('шесть заданий-действий по трём темам', () {
      expect(missionsCatalog.length, greaterThanOrEqualTo(6));
      for (final topic in [
        FinTopic.budget,
        FinTopic.savings,
        FinTopic.purchases,
      ]) {
        expect(missionsCatalog.where((m) => m.topic == topic).length,
            greaterThanOrEqualTo(2));
        expect(lessonsCatalog.where((l) => l.topic == topic).length,
            greaterThanOrEqualTo(2));
      }
    });

    test('действия засчитываются один раз и приносят монеты', () async {
      final game = await readyGame();
      final before = game.balance;
      game.deposit(10);
      expect(game.missionsDone, contains('m_first_save'));
      expect(game.balance, before - 10 + missionReward);
      expect(game.pendingBonusText, contains('Первая монетка'));

      game.deposit(10);
      expect(game.balance, before - 20 + missionReward, reason: 'один раз');

      game.changePlan(BudgetBasket.mandatory, 10);
      game.changePlan(BudgetBasket.optional, 5);
      game.changePlan(BudgetBasket.savings, 5);
      game.confirmPlan();
      expect(game.missionsDone, contains('m_plan'));
    });
  });

  group('2.5.11 справочник', () {
    test('словарик объясняет основные термины', () {
      final words = glossary.map((t) => t.word).join(' ');
      for (final w in ['Бюджет', 'План', 'Факт', 'Копилка', 'цель']) {
        expect(words, contains(w));
      }
    });

    testWidgets('«Как играть» и «Дневник» открываются с главной',
        (tester) async {
      await narrow(tester);
      final game = await readyGame();
      await tester.pumpWidget(FinnyApp(gameState: game));
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(find.text('Как играть'), 200,
          scrollable: find.byType(Scrollable).first);
      await tester.tap(find.text('Как играть'));
      await tester.pumpAndSettle();
      expect(find.text('Потратить на «надо»'), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();

      await tester.tap(find.text('Дневник'));
      await tester.pumpAndSettle();
      expect(find.text('🧾 Сегодня, день 1'), findsOneWidget);
      expect(find.text('Стартовый бюджет'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('2.5.13 сохранение и демо-режим', () {
    test('история, практика, итоги дня и настройки переживают перезапуск',
        () async {
      final game = await readyGame();
      game.deposit(10);
      game.nextDay();
      game.setAnimations(false);
      await game.save();

      final restored = GameState();
      await restored.load();
      expect(restored.journal.length, game.journal.length);
      expect(restored.missionsDone, game.missionsDone);
      expect(restored.lastSummary?.saved, isTrue);
      expect(restored.savingsLog, [10]);
      expect(restored.animationsOn, isFalse);
    });

    test('тестовый профиль сбрасывается к исходному состоянию', () async {
      final game = await readyGame();
      game.deposit(30);
      game.devSkipDays(3);
      await game.startTestProfile();
      expect(game.nickname, 'Тестер');
      expect(game.day, 1);
      expect(game.balance, 60);
      expect(game.savings, 0);
      expect(game.missionsDone, isEmpty);
      expect(game.pet!.type, PetType.cat);
    });

    test('5 периодов подряд без ожидания: доход, траты, рост', () async {
      final game = await readyGame();
      for (var i = 0; i < 5; i++) {
        game.buyItem('apple');
        game.useItem('apple');
        game.deposit(5);
        game.nextDay();
      }
      expect(game.day, 6);
      expect(game.lastSummary!.day, 6);
      expect(game.savings, greaterThan(25), reason: '+ проценты на 5-й день');
      expect(game.pet!.xp, greaterThan(0));
    });
  });

  group('2.5.12 раздел для взрослого', () {
    test('подарок от взрослого — раз в день и с подписью', () async {
      final game = await readyGame();
      final before = game.balance;
      expect(game.giveParentGift(), isTrue);
      expect(game.giveParentGift(), isFalse);
      expect(game.balance, before + parentGift);
      expect(game.todayJournal.first.text, 'Подарок от взрослого');
      game.nextDay();
      expect(game.parentGiftAvailable, isTrue);
    });
  });
}
