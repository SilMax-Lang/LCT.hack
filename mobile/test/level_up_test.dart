import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:finny_pet/app.dart';
import 'package:finny_pet/data/lessons_data.dart';
import 'package:finny_pet/data/shop_data.dart';
import 'package:finny_pet/models/game_state.dart';
import 'package:finny_pet/models/pet.dart';
import 'package:finny_pet/screens/level_up/level_up_screen.dart';
import 'package:finny_pet/theme/kids_theme.dart';
import 'package:finny_pet/widgets/pet_model.dart';

import 'game_fixture.dart';
import 'real_fonts.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() async {
    await useRealFonts();
  });

  test('новый уровень даёт монетки, силы и событие для экрана', () async {
    final game = await readyGame();
    final pet = game.pet!;
    pet.xp = 95;
    pet.hunger = 30;
    pet.happiness = 40;
    pet.cleanliness = 50;
    final balanceBefore = game.balance;

    // Задание даёт 5 опыта — ровно добираем до нового уровня.
    final lesson = lessonsCatalog.first;
    expect(game.answerLesson(lesson.id, lesson.correct).correct, isTrue);

    expect(pet.level, 2, reason: '100 опыта — это новый уровень');
    expect(pet.xp, 0, reason: 'на новом уровне опыт начинается заново');
    expect(pet.hunger, 100);
    expect(pet.happiness, 100);
    expect(pet.cleanliness, 100);
    // +25 за уровень и награда за задание.
    expect(game.balance, balanceBefore + levelUpCoins + lesson.reward);
  });

  test('доход растёт не от уровня, а от курсов', () async {
    final game = await readyGame();
    game.balance = 1000;
    expect(game.baseIncome, 50);

    game.devAddXp(300);
    expect(game.baseIncome, 50, reason: 'уровень доход не меняет');

    final incomes = <int>[];
    for (final course in courses) {
      expect(game.buyItem(course.id), BuyResult.ok);
      incomes.add(game.baseIncome);
    }
    expect(incomes, [60, 75, 95, 120]);
  });

  test('событие роста показывается один раз', () async {
    final game = await readyGame();
    game.pet!.xp = 95;
    game.devAddXp(5);

    final event = game.consumeLevelUp();
    expect(event, isNotNull);
    expect(event!.fromLevel, 1);
    expect(event.toLevel, 2);
    expect(event.coins, levelUpCoins);
    expect(event.levelsGained, 1);
    expect(event.stageFrom, Pet.stageForLevel(1));
    expect(event.stageTo, Pet.stageForLevel(2));
    expect(event.stageChanged, isFalse,
        reason: 'до уровня $teenLevel питомец остаётся малышом');

    expect(game.consumeLevelUp(), isNull,
        reason: 'второй раз показывать нечего');
  });

  test('этапы: малыш до $teenLevel, подросток до $adultLevel, дальше взрослый',
      () async {
    expect(Pet.stageOf(1), PetStage.baby);
    expect(Pet.stageOf(teenLevel - 1), PetStage.baby);
    expect(Pet.stageOf(teenLevel), PetStage.teen);
    expect(Pet.stageOf(adultLevel - 1), PetStage.teen);
    expect(Pet.stageOf(adultLevel), PetStage.adult);

    final game = await readyGame();
    game.pet!.level = teenLevel - 1;
    game.pet!.xp = 95;
    game.devAddXp(5);
    final event = game.consumeLevelUp()!;
    expect(event.stageChanged, isTrue, reason: 'Малыш → Подросток');
  });

  test('без роста уровня события не появляется', () async {
    final game = await readyGame();

    expect(game.deposit(10), isTrue, reason: 'копилка опыта не даёт');
    game.useItem('milk');

    expect(game.pet!.xp, 0);
    expect(game.pet!.level, 1);
    expect(game.consumeLevelUp(), isNull);
  });

  testWidgets('экран нового уровня рисуется на 360dp и закрывается',
      (tester) async {
    await narrow(tester);
    final game = await readyGame();
    // Граница этапа: экран покажет и новый уровень, и «вырос».
    game.pet!.level = teenLevel - 1;
    game.pet!.xp = 95;
    game.devAddXp(5);

    await tester.pumpWidget(GameStateScope(
      notifier: game,
      child: MaterialApp(
        theme: KidsTheme.light(),
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: ElevatedButton(
                onPressed: () => showLevelUpIfNeeded(context),
                child: const Text('действие'),
              ),
            ),
          ),
        ),
      ),
    ));

    await tester.tap(find.text('действие'));
    await tester.pumpAndSettle();

    expect(find.text('НОВЫЙ УРОВЕНЬ!'), findsOneWidget);
    expect(find.text('Уровень $teenLevel'), findsOneWidget);
    expect(find.text('+$levelUpCoins'), findsOneWidget);
    expect(find.text('Барсик вырос: ${Pet.stageForLevel(teenLevel)}'),
        findsOneWidget);
    expect(find.byType(PetModel), findsOneWidget);
    expect(tester.takeException(), isNull,
        reason: 'экран нового уровня переполнился');

    await tester.tap(find.text('Играем дальше! 🚀'));
    await tester.pumpAndSettle();
    expect(find.text('НОВЫЙ УРОВЕНЬ!'), findsNothing);
  });

  testWidgets('новый день на границе уровня сам открывает экран роста',
      (tester) async {
    await narrow(tester);
    final game = await readyGame();
    // Конец дня: питомец сыт и чист — 1 + 3 = 4 опыта, добираем до уровня.
    game.pet!.xp = 97;

    await tester.pumpWidget(FinnyApp(gameState: game));
    await tester.pumpAndSettle();

    await tester.scrollUntilVisible(find.text('Следующий день'), 300,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('Следующий день'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Играем дальше!'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Играем дальше!'));
    await tester.pumpAndSettle();

    expect(find.text('НОВЫЙ УРОВЕНЬ!'), findsOneWidget,
        reason: 'после итогов дня должен открыться экран роста');

    await tester.tap(find.text('Играем дальше! 🚀'));
    await tester.pumpAndSettle();

    // Даём огоньку догореть, чтобы тест не оставил висящих анимаций.
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();
  });
}
