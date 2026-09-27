#!/usr/bin/env python3
"""Build the immutable Chinese Study Curriculum 1.1 dataset.

The runtime never calls an LLM to decide what comes next.  This builder is a
release tool: it combines the HSK 2.0 1-4 canonical lexicon with the lesson
ordering from HSK Standard Course, then attaches pinned natural contexts and
writes a deterministic JSON artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


UNITS = {
    1: ["Знакомство", "Семья и числа", "Время и распорядок", "Еда и места", "Планы и поездки"],
    2: ["Путешествия и распорядок", "Выбор и покупки", "Дом и дорога", "Сравнения", "Опыт и планы"],
    3: ["Планы и перемены", "Люди и отношения", "Сравнение и выбор", "Действия и результат", "Объяснение событий"],
    4: ["Отношения и работа", "Деньги и здоровье", "Взгляд на жизнь", "Общество и образование", "Мир и перемены"],
}

THEMES = {
    1: [
        "Приветствие", "Имя и знакомство", "Учитель и ученик", "Семья и возраст", "Числа и деньги",
        "Языки и умения", "Дата и календарь", "Еда и напитки", "Работа и семья", "Предметы вокруг нас",
        "Где находится предмет", "Время дня", "Погода", "Действие сейчас", "Как мы приехали",
    ],
    2: [
        "Лучшее время для поездки", "Мой обычный день", "Цвета и расположение", "Помощь и знакомые", "Выбор покупки",
        "Завершение действия", "Расстояние до работы", "Обдумать и ответить", "Сделать до конца", "Где лежит телефон",
        "Сравнение людей", "Одежда и погода", "Состояние предмета", "Пережитый опыт", "Скорое событие",
    ],
    3: [
        "Планы на выходные", "Возвращение и время", "Предметы и расположение", "Манера общения", "Постепенное изменение",
        "Неожиданная проблема", "Длительность знакомства", "Условие и выбор", "Одинаковая степень", "Сильное сравнение",
        "Не забыть сделать", "Распорядиться предметом", "Способ движения", "Направление действия", "Проверка результата",
        "Степень состояния", "У каждого есть способ", "Уверенность и согласие", "Заметить по признакам", "Влияние и пассив",
    ],
    4: [
        "Отношения", "Настоящая дружба", "Впечатление на работе", "Карьера и доход", "Разумный выбор",
        "Цена и качество", "Здоровые привычки", "Красота вокруг", "Трудности и надежда", "Что такое счастье",
        "Чтение и развитие", "Внимание к миру", "Традиционное искусство", "Забота о природе", "Воспитание детей",
        "Качество жизни", "Человек и общество", "Безопасность и среда", "Еда и культура", "Путешествие и перемены",
    ],
}

PINYIN_CORRECTIONS = {"起来": "qǐlái"}

# One construction per lexical lesson.  Dependencies are the preceding item,
# so the resulting graph is a transparent acyclic learning path.
GRAMMAR = {
    1: [
        ("Именное предложение с 是", "A 是 B", "Связывает лицо или предмет с названием и ролью."),
        ("Отрицание с 不", "A 不 + глагол/прилагательное", "Отрицает обычное или будущее действие и качество."),
        ("Общий вопрос с 吗", "утверждение + 吗？", "Превращает утверждение в вопрос да/нет."),
        ("Вопросительное 什么", "什么 + существительное", "Запрашивает предмет, имя или вид действия."),
        ("Принадлежность с 的", "A 的 B", "Показывает принадлежность или характеристику."),
        ("Счётное слово 个", "число + 个 + существительное", "Базовая модель количества."),
        ("Глагол 有", "место/лицо + 有 + объект", "Сообщает о наличии или обладании."),
        ("Вопрос сколько с 几", "几 + счётное слово", "Спрашивает небольшое или ожидаемое количество."),
        ("Местонахождение с 在", "A 在 + место", "Показывает, где находится лицо или предмет."),
        ("Где с 哪儿", "A 在哪儿？", "Запрашивает место."),
        ("Время перед сказуемым", "подлежащее + время + сказуемое", "Время обычно ставится до глагола."),
        ("Модальный 会", "会 + глагол", "Выражает приобретённое умение."),
        ("Модальный 能", "能 + глагол", "Выражает возможность или разрешение."),
        ("Желание с 想", "想 + глагол/объект", "Выражает намерение или желание."),
        ("Просьба с 请", "请 + глагольная группа", "Оформляет вежливую просьбу."),
        ("Вопросительное 谁", "谁 + сказуемое？", "Спрашивает о человеке."),
        ("Вопросительное 怎么", "怎么 + глагол？", "Спрашивает о способе действия."),
        ("Наречие 都", "подлежащее + 都 + сказуемое", "Обобщает несколько лиц или предметов."),
        ("Изменение состояния 了", "новая ситуация + 了", "Показывает наступившее изменение."),
        ("Мягкое побуждение 吧", "предложение + 吧", "Оформляет простое совместное предложение или мягкую просьбу."),
    ],
    2: [
        ("Завершённость 了", "глагол + 了 + объект", "Сообщает о завершённом действии."),
        ("Отрицание прошлого 没", "没(有) + глагол", "Отрицает совершившееся действие."),
        ("Последовательность 先…再…", "先 A，再 B", "Упорядочивает два действия."),
        ("Продолжительность действия", "глагол + длительность", "Показывает, сколько длилось действие."),
        ("Частотность 常常", "常常 + глагол", "Говорит о регулярном действии."),
        ("正在: действие сейчас", "正在 + глагол + 呢", "Подчёркивает процесс в момент речи."),
        ("Интонационный вопрос 呢", "A 呢？", "Возвращает вопрос или спрашивает о состоянии."),
        ("Предложение с 吧", "фраза + 吧", "Смягчает предложение, просьбу или предположение."),
        ("Запрет с 别", "别 + глагол + 了", "Просит не делать действие."),
        ("Сравнение с 比", "A 比 B + прилагательное", "Сравнивает два объекта по признаку."),
        ("Разница в количестве", "A 比 B + прил. + число", "Уточняет величину различия."),
        ("Самая высокая степень 最", "最 + прилагательное", "Выделяет максимальную степень."),
        ("Ещё более 更", "更 + прилагательное", "Усиливает сравниваемое качество."),
        ("Степень с 得", "глагол + 得 + описание", "Описывает качество выполнения действия."),
        ("Состояние с 着", "глагол + 着", "Показывает сохраняющееся состояние."),
        ("Опыт с 过", "глагол + 过", "Сообщает, что опыт случался хотя бы раз."),
        ("Скорое событие 要…了", "要/快要…了", "Показывает, что событие скоро наступит."),
        ("Причина 因为…所以…", "因为 A，所以 B", "Связывает причину со следствием."),
        ("Условие 如果…就…", "如果 A，就 B", "Формулирует условие и ожидаемый результат."),
        ("Кроме 还", "подлежащее + 还 + сказуемое", "Добавляет ещё одно действие, свойство или предмет."),
    ],
    3: [
        ("Всё ещё 还", "还 + глагол/прилагательное", "Показывает продолжение состояния."),
        ("Уже 已经…了", "已经 + сказуемое + 了", "Подчёркивает достигнутое состояние."),
        ("Сначала 然后", "A，然后 B", "Связывает последовательные события."),
        ("Одновременность 一边…一边…", "一边 A，一边 B", "Два действия идут одновременно."),
        ("Как только 一…就…", "一 A，就 B", "Второе действие следует сразу за первым."),
        ("Чем… тем… 越…越…", "越 A 越 B", "Показывает совместное постепенное изменение."),
        ("Постепенно 越来越", "越来越 + прилагательное", "Показывает нарастание признака."),
        ("Не только 不但…而且…", "不但 A，而且 B", "Добавляет более сильный второй факт."),
        ("Хотя 虽然…但是…", "虽然 A，但是 B", "Противопоставляет результат условию."),
        ("Кроме 除了…以外…", "除了 A 以外，还 B", "Добавляет элемент за пределами названного."),
        ("И… и… 又…又…", "又 A 又 B", "Соединяет два одновременных качества."),
        ("То… то… 有时…有时…", "有时 A，有时 B", "Чередует ситуации."),
        ("Или 还是 в вопросе", "A 还是 B？", "Предлагает выбор в вопросе."),
        ("Либо 或者", "A 或者 B", "Соединяет варианты в утверждении."),
        ("Одинаковая степень 一样", "A 跟 B 一样 + прил.", "Показывает равенство признака."),
        ("Не такой как 没有", "A 没有 B + прил.", "Показывает меньшую степень."),
        ("Намного …得多", "прилагательное + 得多", "Усиливает различие в сравнении."),
        ("Примерное число 多", "число + 多 + счётное слово", "Показывает немного больше названного числа."),
        ("Примерность 左右", "число + 左右", "Показывает приблизительное количество."),
        ("Риторическое 不是…吗", "不是…吗？", "Напоминает об очевидном или известном."),
        ("Утверждение 是…的", "是 + обстоятельство + 的", "Выделяет деталь прошедшего действия."),
        ("Результат 看完", "глагол + результативное дополнение", "Показывает достигнутый результат."),
        ("Результат 好/到", "глагол + 好/到", "Показывает готовность или достижение."),
        ("Возможность 看得懂", "глагол + 得/不 + результат", "Показывает достижимость результата."),
        ("Направление 来/去", "глагол + 来/去", "Показывает движение к говорящему или от него."),
        ("Сложное направление", "глагол + 上/下/进/出 + 来/去", "Уточняет траекторию движения."),
        ("Конструкция 把", "A 把 B + глагол + результат", "Выносит определённый объект перед действием."),
        ("把 с направлением", "把 B + глагол + направление", "Показывает перемещение объекта."),
        ("Пассив с 被", "A 被 B + глагол", "Показывает действие над подлежащим."),
        ("Пассив без деятеля", "A 被 + глагол + результат", "Опускает неизвестного деятеля."),
        ("Степень до результата", "прилагательное + 得 + предложение", "Показывает следствие высокой степени."),
        ("Даже 连…都…", "连 A 都/也 B", "Выделяет неожиданный крайний случай."),
        ("Только 才", "условие/время + 才 + действие", "Показывает позднее или ограниченное наступление."),
        ("Уже 就", "условие/время + 就 + действие", "Показывает раннее или быстрое наступление."),
        ("Именно 就是", "就是 + выделяемая часть", "Уточняет и фокусирует информацию."),
        ("Оказывается 原来", "原来 + новая информация", "Вводит обнаруженное объяснение."),
        ("По-прежнему 还是", "还是 + сказуемое", "Показывает сохранение выбора или состояния."),
        ("О любом 谁都", "疑问词 + 都", "Обобщает: любой человек, место или предмет."),
    ],
    4: [
        ("В отношении 对于", "对于 A，B", "Задаёт тему или объект оценки."),
        ("Что касается 关于", "关于 A 的 B", "Связывает сообщение с темой."),
        ("Согласно 根据", "根据 A，B", "Указывает источник вывода."),
        ("В соответствии 按照", "按照 A + действие", "Показывает правило или порядок."),
        ("Посредством 通过", "通过 A，达到 B", "Называет способ достижения результата."),
        ("Из-за 由于", "由于 A，B", "Вводит формальную причину."),
        ("Поэтому 因此", "A，因此 B", "Вводит формальное следствие."),
        ("Тем самым 从而", "A，从而 B", "Показывает логический результат процесса."),
        ("Иначе 否则", "A，否则 B", "Предупреждает об альтернативном результате."),
        ("Если только 只要…就…", "只要 A，就 B", "Называет достаточное условие."),
        ("Только если 只有…才…", "只有 A，才 B", "Называет необходимое условие."),
        ("Независимо от 无论…都…", "无论 A，都 B", "Показывает неизменный результат при разных условиях."),
        ("Даже если 即使…也…", "即使 A，也 B", "Сохраняет результат вопреки условию."),
        ("Раз уж 既然…就…", "既然 A，就 B", "Выводит решение из принятого факта."),
        ("Пока 只要", "只要 + состояние", "Ограничивает условие минимальным требованием."),
        ("Вместо 与其…不如…", "与其 A，不如 B", "Предпочитает второй из двух вариантов."),
        ("Скорее 宁可…也不…", "宁可 A，也不 B", "Выражает сильное предпочтение."),
        ("Не то чтобы 不是…而是…", "不是 A，而是 B", "Исправляет неверное объяснение."),
        ("С одной стороны 一方面", "一方面 A，另一方面 B", "Сопоставляет две стороны вопроса."),
        ("Кроме того 此外", "A，此外 B", "Добавляет отдельный аргумент."),
        ("Более того 而且", "A，而且 B", "Добавляет усиливающий факт."),
        ("Особенно 尤其", "A，尤其是 B", "Выделяет наиболее характерный пример."),
        ("Например 例如", "例如 + пример", "Вводит конкретный пример."),
        ("Включая 包括", "A 包括 B", "Перечисляет состав целого."),
        ("Среди них 其中", "其中 + часть", "Выделяет часть ранее названного множества."),
        ("Соответственно 分别", "A 和 B 分别…", "Распределяет действия по участникам."),
        ("Друг за другом 陆续", "陆续 + глагол", "Показывает последовательное участие разных лиц."),
        ("Постепенно 逐渐", "逐渐 + изменение", "Описывает плавное развитие."),
        ("Наконец 终于", "终于 + результат", "Подчёркивает достигнутый после ожидания результат."),
        ("Неожиданно 竟然", "竟然 + факт", "Показывает неожиданность."),
        ("В итоге 结果", "原因，结果 + итог", "Вводит фактический итог."),
        ("Изначально 本来", "本来 A，可是 B", "Противопоставляет исходный план факту."),
        ("На самом деле 实际上", "实际上 + уточнение", "Исправляет впечатление фактами."),
        ("По-видимому 看来", "看来 + вывод", "Вводит вывод по наблюдениям."),
        ("Похоже 好像", "好像 + предположение", "Выражает неуверенное сходство или вывод."),
        ("Возможно 也许", "也许 + предположение", "Выражает вероятность."),
        ("Вероятно 可能", "可能 + глагольная группа", "Показывает возможность события."),
        ("Обязательно 一定", "一定 + глагол", "Выражает уверенность или обязательность."),
        ("Совсем не 并不", "并不 + сказуемое", "Усиливает отрицание ожидания."),
        ("Не обязательно 不一定", "不一定 + сказуемое", "Снимает категоричность вывода."),
        ("Почти 差点儿", "差点儿 + нежелательный результат", "Показывает, что событие едва не случилось."),
        ("Чуть не 几乎", "几乎 + глагол/все", "Показывает близость к пределу."),
        ("Примерно 大约", "大约 + количество", "Даёт приблизительную оценку."),
        ("Более чем 超过", "超过 + число/объект", "Показывает превышение границы."),
        ("Менее чем 不到", "不到 + число/время", "Показывает недостижение границы."),
        ("Достигать 达到", "达到 + показатель", "Называет достигнутый уровень."),
        ("Занимать 占", "A 占 B 的…", "Показывает долю в целом."),
        ("Увеличиться на", "增加了 + количество", "Показывает абсолютное увеличение."),
        ("Увеличиться до", "增加到 + результат", "Показывает новый итоговый уровень."),
        ("Вдвое 倍", "是原来的 + число + 倍", "Сравнивает кратные величины."),
        ("Процент 百分之", "百分之 + число", "Выражает долю в процентах."),
        ("Пассив 给", "A 给 B + глагол", "Разговорная пассивная конструкция."),
        ("Пассив 让", "A 让 B + глагол", "Показывает вызванное действие или состояние."),
        ("Побуждение 使", "A 使 B + результат", "Формально выражает причинение результата."),
        ("Позволить 让", "让 + лицо + глагол", "Передаёт разрешение или поручение."),
        ("Заставить 叫", "叫 + лицо + глагол", "Передаёт распоряжение в разговорной речи."),
        ("Расширенное 把", "把 B + глагол + 得 + результат", "Выделяет результат воздействия на объект."),
        ("把 с 给", "把 B 给 + глагол", "Разговорно усиливает распоряжение объектом."),
        ("Даже до 甚至", "甚至 + крайний факт", "Добавляет неожиданный крайний случай."),
        ("Вплоть до 直到", "直到 A，才 B", "Показывает позднюю границу наступления."),
        ("С тех пор 自从", "自从 A 以后，B", "Задаёт начальную точку длительного состояния."),
        ("До того как 在…之前", "在 A 之前，B", "Располагает событие раньше другого."),
        ("После того как …以后", "A 以后，B", "Располагает событие после другого."),
        ("Одновременно 同时", "A，同时 B", "Связывает одновременные факты."),
        ("В процессе 当…时", "当 A 的时候，B", "Задаёт временной фон."),
        ("По мере 随着", "随着 A，B", "Показывает изменение вместе с процессом."),
        ("Один за другим 一个接一个", "一个接一个地 + глагол", "Показывает непрерывную последовательность."),
        ("Повторное 再", "再 + глагол", "Показывает будущее повторение."),
        ("Снова 又", "又 + глагол + 了", "Показывает случившееся повторение."),
        ("Напротив 反而", "A，反而 B", "Вводит результат, противоположный ожиданию."),
        ("Однако 却", "A，却 B", "Кратко противопоставляет неожиданный факт."),
        ("Тем не менее 不过", "A，不过 B", "Добавляет мягкое ограничение."),
        ("При этом 而", "A，而 B", "Формально соединяет контрастные части."),
        ("Итоговое 总之", "总之 + вывод", "Суммирует рассуждение."),
        ("Можно сказать 可以说", "可以说 + вывод", "Вводит обобщённую оценку или итоговый вывод."),
    ],
}


def partition(items: list, low: int = 7, high: int = 10) -> list[list]:
    """Partition while guaranteeing 7..10 items per non-review lesson."""
    n = len(items)
    # Eight words is the pedagogical default.  Seven, nine and ten are used
    # only when a thematic unit cannot be split into exact groups of eight.
    parts = max(1, round(n / 8))
    while math.ceil(n / parts) > high:
        parts += 1
    while parts > 1 and n // parts < low:
        parts -= 1
    sizes = [n // parts + (1 if i < n % parts else 0) for i in range(parts)]
    assert all(low <= size <= high for size in sizes), (n, sizes)
    out, pos = [], 0
    for size in sizes:
        out.append(items[pos:pos + size])
        pos += size
    return out


def clean_translation(word: dict) -> str:
    rus = [x.strip() for x in word.get("translations", {}).get("rus", []) if x.strip()]
    eng = [x.strip() for x in word.get("translations", {}).get("eng", []) if x.strip()]
    return "; ".join((rus or eng)[:2])


def example_for(word: dict) -> dict:
    h, p, tr = word["hanzi"], PINYIN_CORRECTIONS.get(word["hanzi"], word["pinyin"]), clean_translation(word)
    # Natural examples replace this lexical fallback during the enrichment pass.
    return {"cn": h, "pinyin": p, "ru": tr}


def load_order(csv_dir: Path, level: int) -> dict[str, float]:
    paths = [csv_dir / f"HSK Standard Course Vocabulary - hsk_{level}.csv"]
    if level == 4:
        paths = [csv_dir / "HSK Standard Course Vocabulary - hsk_4a.csv", csv_dir / "HSK Standard Course Vocabulary - hsk_4b.csv"]
    order, serial = {}, 0
    for path in paths:
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("Type") != "New Word":
                    continue
                serial += 1
                try:
                    lesson_number = int(str(row.get("Lesson", "")).split(".")[-1])
                except ValueError:
                    lesson_number = len(THEMES[level])
                # CSV rows are alphabetic, not pedagogical.  The explicit
                # textbook lesson number is therefore the primary sort key.
                order.setdefault(row["Word/Phrase"], lesson_number * 10000 + serial)
    return order


def choice_options(words: list[dict], answer: dict) -> list[str]:
    vals = [clean_translation(answer)]
    for word in words:
        val = clean_translation(word)
        if word["id"] != answer["id"] and val and val not in vals:
            vals.append(val)
        if len(vals) == 4:
            break
    while len(vals) < 4:
        vals.append(f"другой вариант {len(vals)}")
    return vals


def hanzi_options(words: list[dict], answer: dict) -> list[str]:
    vals = [answer["hanzi"]]
    for word in words:
        value = word["hanzi"]
        if value not in vals:
            vals.append(value)
        if len(vals) == 4:
            break
    return vals


def build(args: argparse.Namespace) -> dict:
    lexicon = json.loads(Path(args.lexicon).read_text(encoding="utf-8"))
    levels, grammar_cursor, global_order = [], defaultdict(int), 0
    prior_grammar: list[str] = []
    for level in range(1, 5):
        canonical = [w for w in lexicon if int(w["level"]) == level]
        hanzi_counts = Counter(w["hanzi"] for w in canonical)
        order = load_order(Path(args.course_csv_dir), level)
        canonical.sort(key=lambda w: (order.get(w["hanzi"], 100000 + int(w["id"])), int(w["id"])))
        # Standard Course has five coherent units: three source lessons per
        # unit for HSK1/2 and four per unit for HSK3/4.  Canonical words absent
        # in the textbook appendix remain at the end of the nearest unit.
        boundaries = 3 if level < 3 else 4
        unit_buckets = [[] for _ in range(5)]
        for word in canonical:
            source_pos = order.get(word["hanzi"])
            if source_pos is None:
                idx = min(4, int(word["id"]) % 5)
            else:
                source_lesson = min(len(THEMES[level]), max(1, int(source_pos // 10000)))
                idx = min(4, (source_lesson - 1) // boundaries)
            unit_buckets[idx].append(word)
        level_obj = {"id": f"hsk{level}", "hsk_level": level, "title": f"HSK {level}", "units": []}
        level_lesson_no = 0
        for unit_index, bucket in enumerate(unit_buckets, 1):
            unit = {"id": f"h{level}-u{unit_index}", "number": unit_index, "title": UNITS[level][unit_index - 1], "lessons": []}
            chunks = partition(bucket)
            for part_index, chunk in enumerate(chunks, 1):
                level_lesson_no += 1
                global_order += 1
                grammar_index = grammar_cursor[level]
                grammar_cursor[level] += 1
                title, pattern, explanation = GRAMMAR[level][grammar_index]
                grammar_id = f"h{level}-g{grammar_index + 1:02d}"
                prereq = [prior_grammar[-1]] if prior_grammar else []
                source_lessons = [int(order[w["hanzi"]] // 10000) for w in chunk if w["hanzi"] in order]
                source_lesson = Counter(source_lessons).most_common(1)[0][0] if source_lessons else min(len(THEMES[level]), (unit_index - 1) * boundaries + 1)
                lesson_title = THEMES[level][source_lesson - 1]
                if len(chunks) > 1:
                    lesson_title += f" · часть {part_index}"
                vocab = []
                for word in chunk:
                    item = {
                        "id": f"h{level}-w{int(word['id']):04d}",
                        "hanzi": word["hanzi"], "pinyin": PINYIN_CORRECTIONS.get(word["hanzi"], word["pinyin"]),
                        "translation_ru": clean_translation(word), "example": example_for(word),
                    }
                    if hanzi_counts[word["hanzi"]] > 1:
                        item["duplicate_reason"] = "Отдельная словарная статья: другое значение или часть речи."
                    vocab.append(item)
                first, second = chunk[0], chunk[min(1, len(chunk) - 1)]
                sample_cn = f"今天我们先学习{first['hanzi']}，然后练习{second['hanzi']}。"
                first_pinyin = PINYIN_CORRECTIONS.get(first["hanzi"], first["pinyin"])
                second_pinyin = PINYIN_CORRECTIONS.get(second["hanzi"], second["pinyin"])
                sample_py = f"Jīntiān wǒmen xiān xuéxí {first_pinyin}，ránhòu liànxí {second_pinyin}。"
                options = choice_options(chunk + canonical, first)
                lesson = {
                    "id": f"h{level}-u{unit_index}-l{part_index}", "type": "lesson", "hsk_level": level,
                    "unit_id": unit["id"], "unit": unit_index, "number": level_lesson_no, "order": global_order,
                    "title": lesson_title,
                    "objective": f"Освоить лексику темы «{lesson_title.split(' ·')[0]}» и конструкцию «{title}».",
                    "estimated_minutes": 12, "vocabulary": vocab,
                    "grammar": {"id": grammar_id, "title": title, "pattern": pattern, "explanation_ru": explanation, "prerequisites": prereq},
                    "grammar_prerequisites": prereq, "review_grammar_ids": prior_grammar[-3:],
                    "examples": [v["example"] for v in vocab[:4]],
                    "dialogue": {
                        "cn": f"A：今天学什么？\nB：先学{first['hanzi']}，再学{second['hanzi']}。\nA：好，我们开始吧。",
                        "pinyin": f"A: Jīntiān xué shénme?\nB: Xiān xué {first_pinyin}, zài xué {second_pinyin}.\nA: Hǎo, wǒmen kāishǐ ba.",
                        "ru": f"— Что сегодня учим? — Сначала «{first['hanzi']}», затем «{second['hanzi']}». — Хорошо, начнём.",
                    },
                    "exercises": {
                        "listening": [{"audio_text": sample_cn, "question_ru": "Какое слово прозвучало первым?", "options": hanzi_options(chunk + canonical, first), "answer": first["hanzi"], "pinyin": sample_py}],
                        "comprehension": [{"text_cn": sample_cn, "text_pinyin": sample_py, "question_ru": f"Что означает {first['hanzi']}?", "options": options, "answer": clean_translation(first)}],
                        "reading": [{"text_cn": sample_cn, "text_pinyin": sample_py, "question_ru": "Что делают сначала?", "answer": first["hanzi"]}],
                        "choice": [{"question_ru": clean_translation(first), "options": hanzi_options(chunk + canonical, first), "answer": first["hanzi"]}],
                        "word_order": [{"tokens": ["我们", "今天", "学习", first["hanzi"]], "answer": f"我们今天学习{first['hanzi']}。", "pinyin": f"Wǒmen jīntiān xuéxí {first_pinyin}."}],
                        "fill_blank": [{"sentence": f"今天我们学习___这个词。", "answer": first["hanzi"], "pinyin": f"Jīntiān wǒmen xuéxí {first_pinyin} zhège cí."}],
                        "translation_ru_cn": [{"prompt_ru": clean_translation(second), "answers": [second["hanzi"]], "pinyin": second_pinyin}],
                        "active_answer": [{"prompt_ru": f"Составьте короткую фразу со словом «{first['hanzi']}». Потом сравните с примером.", "sample_cn": first["hanzi"], "sample_pinyin": first_pinyin}],
                    },
                    "srs_items": [*[{"type": "vocabulary", "id": v["id"]} for v in vocab], {"type": "grammar", "id": grammar_id}],
                }
                unit["lessons"].append(lesson)
                prior_grammar.append(grammar_id)
            level_lesson_no += 1
            global_order += 1
            review_ids = [l["id"] for l in unit["lessons"]]
            unit["lessons"].append({
                "id": f"h{level}-u{unit_index}-review", "type": "review", "hsk_level": level,
                "unit_id": unit["id"], "unit": unit_index, "number": level_lesson_no, "order": global_order,
                "title": f"Контроль: {unit['title']}", "objective": "Закрепить лексику и грамматику раздела в смешанных заданиях.",
                "estimated_minutes": 10, "vocabulary": [], "grammar": None, "grammar_prerequisites": prior_grammar[-4:],
                "review_grammar_ids": prior_grammar[-6:], "review_lesson_ids": review_ids, "examples": [],
                "dialogue": {"cn": "复习以后，我们继续学习。", "pinyin": "Fùxí yǐhòu, wǒmen jìxù xuéxí.", "ru": "После повторения продолжаем учиться."},
                "exercises": {"listening": [], "comprehension": [], "reading": [], "choice": [], "word_order": [], "fill_blank": [], "translation_ru_cn": [], "active_answer": []},
                "srs_items": [{"type": "grammar", "id": x} for x in prior_grammar[-6:]],
            })
            level_obj["units"].append(unit)
        levels.append(level_obj)
    return {
        "version": "1.1.0", "schema_version": 1,
        "standard": "HSK 2.0 levels 1-4; lesson sequencing follows HSK Standard Course 1-4",
        "generated_by": "deterministic release builder; no runtime AI sequencing",
        "levels": levels,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lexicon", required=True)
    parser.add_argument("--course-csv-dir", required=True)
    parser.add_argument("--sentences", required=True, help="no7z/hsk-sentences-audio dist/sentences.json")
    parser.add_argument("--sentence-source-commit", default="857dfbab91027ebd97df01260e91b817cb6b4854")
    parser.add_argument("--output", default="curriculum/curriculum-v1.json")
    args = parser.parse_args()
    data = build(args)
    from enrich_contexts import enrich
    sentences = json.loads(Path(args.sentences).read_text(encoding="utf-8"))
    data = enrich(data, sentences, args.sentence_source_commit)
    Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
