import 'package:flutter/material.dart';

import '../../app.dart';
import '../../data/shop_data.dart';
import '../../models/game_state.dart';
import '../../models/pet.dart';
import '../../theme/kids_theme.dart';
import '../../widgets/action_spark.dart';
import '../../widgets/kids_button.dart';
import '../../widgets/loop_carousel.dart';
import '../../widgets/pet_poster_card.dart';

/// Магазин по документам «Игровая экономика»:
/// - перекраска питомца и скидка дня;
/// - «Надо»: еда, уход, здоровье, вещи для дома (миска, поилка, лежанка —
///   покупаются один раз);
/// - «Хочу»: игрушки и коллекция из 20 украшений (продаются за 70 %);
/// - «Обучение»: курсы по порядку, каждый повышает доход за день.
///
/// Каждая покупка — через окно «Купить / Отменить». Пока питомец голоден
/// (сытость ≤ 40), игрушки и обучение закрыты: сначала накорми.
/// Баланс — в верхней панели (MainShell), виден при прокрутке.
class ShopScreen extends StatefulWidget {
  const ShopScreen({super.key});

  @override
  State<ShopScreen> createState() => _ShopScreenState();
}

class _ShopScreenState extends State<ShopScreen> {
  /// Счётчики вспышек: «огонёк» играет на той покупке, которую сделали.
  final Map<String, int> _sparks = {};

  /// Выбранный отдел; null — «Все».
  ItemKind? _kind;

  void _spark(String id) =>
      setState(() => _sparks[id] = (_sparks[id] ?? 0) + 1);

  /// Покупка — только после подтверждения: видно, сколько останется.
  Future<void> _buy(ShopItem item) async {
    final game = GameStateScope.read(context);
    final price = game.priceOf(item);
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('${item.emoji} ${item.title}'),
        content: Text(
          'Купить за $price 🪙?\n'
          'В кошельке останется ${game.balance - price} 🪙.'
          '${item.permanent ? '\nЭто покупка навсегда.' : ''}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Отменить'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Купить'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    if (game.buyItem(item.id) == BuyResult.ok) _spark(item.id);
  }

  /// Продажа украшения — тоже с подтверждением.
  Future<void> _sell(ShopItem item) async {
    final game = GameStateScope.read(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('Продать «${item.title}»?'),
        content: Text(
          'Магазин заплатит ${item.resalePrice} 🪙 — это 70 % цены '
          '(купили за ${item.price}).',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Оставить'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Продать'),
          ),
        ],
      ),
    );
    if (ok == true && mounted) game.sellDecoration(item.id);
  }

  void _recolor(PetVariant variant) {
    if (GameStateScope.read(context).recolorPet(variant)) _spark('recolor');
  }

  @override
  Widget build(BuildContext context) {
    final game = GameStateScope.of(context);
    final deal = dealOfDay(game.day);
    final kinds = _kind == null ? ItemKind.values : [_kind!];

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (game.pet != null)
          _RecolorSection(
            game: game,
            spark: _sparks['recolor'] ?? 0,
            onRecolor: _recolor,
          ),
        if (game.petHungry) ...[
          const SizedBox(height: 12),
          _HungryNote(petName: game.pet?.name ?? 'Питомец'),
        ],
        const SizedBox(height: 12),
        _DealCard(
          item: deal,
          price: game.priceOf(deal),
          spark: _sparks[deal.id] ?? 0,
          onBuy: game.canBuy(deal) == BuyResult.ok ? () => _buy(deal) : null,
        ),
        const SizedBox(height: 12),
        // Отделы: горизонтальная лента чипов, крупных для пальца.
        SizedBox(
          height: 48,
          child: ListView(
            scrollDirection: Axis.horizontal,
            children: [
              _KindChip(
                label: '🛍️ Все',
                selected: _kind == null,
                onTap: () => setState(() => _kind = null),
              ),
              ...ItemKind.values.map(
                (k) => _KindChip(
                  label: '${k.emoji} ${k.title}',
                  selected: _kind == k,
                  onTap: () => setState(() => _kind = k),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        for (final kind in kinds) ..._section(game, kind),
      ],
    );
  }

  List<Widget> _section(GameState game, ItemKind kind) {
    final items = shopCatalog.where((i) => i.kind == kind).toList();
    final String subtitle;
    switch (kind) {
      case ItemKind.home:
        subtitle = 'Покупается один раз и остаётся навсегда';
      case ItemKind.education:
        subtitle = 'Курсы по порядку. Сейчас доход ${game.baseIncome} 🪙 в день';
      case ItemKind.decor:
        final have = items.where((i) => game.owned.contains(i.id)).length;
        subtitle = 'Коллекция: $have из ${items.length}. Продажа — за 70 %';
      default:
        subtitle = '';
    }
    return [
      Row(
        children: [
          Expanded(
            child: Text(
              '${kind.emoji} ${kind.title}',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
          ),
          _NeedTag(kind: kind),
        ],
      ),
      if (subtitle.isNotEmpty)
        Text(subtitle, style: TextStyle(color: KidsTheme.muted(context))),
      const SizedBox(height: 8),
      for (final item in items) _card(game, item),
      const SizedBox(height: 6),
    ];
  }

  Widget _card(GameState game, ShopItem item) {
    final status = game.canBuy(item);
    final price = game.priceOf(item);
    final owned = game.owned.contains(item.id);
    String label = '🪙 $price';
    VoidCallback? onPressed = status == BuyResult.ok ? () => _buy(item) : null;
    String? note;
    switch (status) {
      case BuyResult.owned:
        if (item.kind == ItemKind.decor) {
          label = 'Продать';
          onPressed = () => _sell(item);
        } else {
          label = 'Есть ✅';
        }
      case BuyResult.locked:
        label = '🔒 $price';
        note = 'Сначала пройди предыдущий курс';
      case BuyResult.hungry:
        note = 'Сначала накорми питомца';
      case BuyResult.noMoney:
      case BuyResult.ok:
        break;
    }
    return _ItemCard(
      item: item,
      count: item.permanent ? (owned ? 1 : 0) : game.inventory[item.id] ?? 0,
      price: price,
      spark: _sparks[item.id] ?? 0,
      label: label,
      onPressed: onPressed,
      note: note,
    );
  }
}

/// Питомец голоден: игрушки и обучение закрыты (текстом, не только цветом).
class _HungryNote extends StatelessWidget {
  final String petName;

  const _HungryNote({required this.petName});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFF7043).withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Text(
        '😋 $petName слишком голоден, чтобы играть или учиться! '
        'Сначала накорми его.',
        style: const TextStyle(fontWeight: FontWeight.w600),
      ),
    );
  }
}

/// Перекраска питомца: та же карусель, что в начале игры. Листаешь —
/// видишь питомца в новом цвете (постер его нынешнего возраста),
/// нажимаешь «Перекрасить» — и он такой на главном экране.
class _RecolorSection extends StatefulWidget {
  final GameState game;
  final int spark;
  final ValueChanged<PetVariant> onRecolor;

  const _RecolorSection({
    required this.game,
    required this.spark,
    required this.onRecolor,
  });

  @override
  State<_RecolorSection> createState() => _RecolorSectionState();
}

class _RecolorSectionState extends State<_RecolorSection> {
  late PetVariant _shown = widget.game.pet!.variant;

  @override
  Widget build(BuildContext context) {
    final pet = widget.game.pet!;
    final current = _shown == pet.variant;
    final afford = widget.game.balance >= recolorPrice;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          '🎨 Окраска питомца',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        SparkOnAction(
          trigger: widget.spark,
          spread: 70,
          child: LoopCarousel(
            itemCount: PetVariant.values.length,
            initialIndex: pet.variant.index,
            height: 230,
            onChanged: (i) => setState(() => _shown = PetVariant.values[i]),
            itemBuilder: (context, i, selected) {
              final variant = PetVariant.values[i];
              return PetPosterCard(
                type: pet.type,
                variant: variant,
                level: pet.level,
                title: PetLook.of(pet.type, variant).label,
                selected: variant == pet.variant,
                subtitle: '🪙 $recolorPrice',
              );
            },
          ),
        ),
        const SizedBox(height: 4),
        KidsButton(
          text: current
              ? 'Сейчас такой'
              : 'Перекрасить за $recolorPrice 🪙',
          icon: current ? null : Icons.brush_outlined,
          onPressed: current || !afford ? null : () => widget.onRecolor(_shown),
        ),
      ],
    );
  }
}

/// Строка пользы: «🍎 +20  😊 +5», у курса — новый доход, у украшения —
/// редкость. Видно без чтения описания.
String effectsLine(ShopItem item) {
  if (item.incomeAfter != null) return '📈 Доход ${item.incomeAfter} в день';
  if (item.rarity != null) return item.rarity!.title;
  final parts = <String>[
    if (item.hunger > 0) '🍎 +${item.hunger}',
    if (item.happiness > 0) '😊 +${item.happiness}',
    if (item.cleanliness > 0) '🧼 +${item.cleanliness}',
  ];
  return parts.isEmpty ? item.effectText : parts.join('   ');
}

class _ItemCard extends StatelessWidget {
  final ShopItem item;
  final int count;
  final int price;
  final int spark;
  final String label;
  final VoidCallback? onPressed;

  /// Почему кнопка закрыта (голод, порядок курсов) — текстом.
  final String? note;

  const _ItemCard({
    required this.item,
    required this.count,
    required this.price,
    required this.spark,
    required this.label,
    required this.onPressed,
    this.note,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final discounted = price != item.price;
    final rarity = item.rarity;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              // Огонёк вспыхивает на купленном предмете.
              SparkOnAction(
                trigger: spark,
                spread: 30,
                child: Container(
                  width: 56,
                  height: 56,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: rarity?.color.withValues(alpha: 0.15) ??
                        KidsTheme.soft(context),
                    borderRadius: BorderRadius.circular(16),
                    border: rarity == null
                        ? null
                        : Border.all(color: rarity.color, width: 2),
                  ),
                  child: Text(item.emoji, style: const TextStyle(fontSize: 32)),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${item.title}'
                      '${!item.permanent && count > 0 ? ' × $count' : ''}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    ),
                    if (item.badge != null || discounted)
                      Padding(
                        padding: const EdgeInsets.only(top: 2, bottom: 2),
                        child: _Badge(
                          text: discounted ? '🔥 −$dealPercent%' : item.badge!,
                        ),
                      ),
                    Text(
                      note ?? effectsLine(item),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: note != null
                            ? const Color(0xFFD84315)
                            : scheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                  // ТЗ: тач-таргет не меньше 48x48dp.
                  minimumSize: const Size(84, 48),
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                ),
                onPressed: onPressed,
                child: Text(label),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Большая карточка «Скидка дня».
class _DealCard extends StatelessWidget {
  final ShopItem item;
  final int price;
  final int spark;
  final VoidCallback? onBuy;

  const _DealCard({
    required this.item,
    required this.price,
    required this.spark,
    required this.onBuy,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFFFFB547), Color(0xFFFF7A59)],
        ),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              SparkOnAction(
                trigger: spark,
                spread: 34,
                child:
                    Text(item.emoji, style: const TextStyle(fontSize: 44)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '🔥 Скидка дня −$dealPercent%',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    Text(
                      item.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text(
                      'Было ${item.price} 🪙',
                      style: const TextStyle(
                        color: Colors.white,
                        decoration: TextDecoration.lineThrough,
                        decorationColor: Colors.white,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.white,
              foregroundColor: const Color(0xFFD9480F),
              minimumSize: const Size(48, 48),
            ),
            onPressed: onBuy,
            child: Text('Купить за $price 🪙'),
          ),
        ],
      ),
    );
  }
}

class _KindChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _KindChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(24),
        child: Container(
          constraints: const BoxConstraints(minHeight: 48),
          padding: const EdgeInsets.symmetric(horizontal: 16),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: selected ? scheme.primary : KidsTheme.pill(context),
            borderRadius: BorderRadius.circular(24),
            border: Border.all(
              color: selected ? scheme.primary : scheme.outline,
            ),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontWeight: FontWeight.bold,
              color: selected ? Colors.white : scheme.onSurface,
            ),
          ),
        ),
      ),
    );
  }
}

/// «Надо» / «Хочу» — текстом, а не только цветом (требование ТЗ).
/// Корзина отдела: «Надо», «Хочу» или «Обучение» — текстом, а не только
/// цветом (требование ТЗ).
class _NeedTag extends StatelessWidget {
  final ItemKind kind;

  const _NeedTag({required this.kind});

  @override
  Widget build(BuildContext context) {
    final basket = kind.basket;
    final color = basket.color;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(
        '${basket.emoji} ${basket.title}',
        style: TextStyle(
          fontWeight: FontWeight.bold,
          color: KidsTheme.isDark(context) ? Colors.white : color,
        ),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final String text;

  const _Badge({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: const Color(0xFFFFE3B3),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: const TextStyle(
          color: Color(0xFF8A4B00),
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }
}
