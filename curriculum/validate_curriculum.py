#!/usr/bin/env python3
"""Strict validator and coverage report for Curriculum 1.0."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_WORDS = {1: 150, 2: 150, 3: 299, 4: 601}
REQUIRED_LESSON = {
    "id", "type", "hsk_level", "unit", "number", "title", "objective",
    "estimated_minutes", "vocabulary", "grammar_prerequisites",
    "review_grammar_ids", "examples", "dialogue", "exercises", "srs_items",
}
REQUIRED_EXERCISES = {
    "listening", "comprehension", "reading", "choice", "word_order",
    "fill_blank", "translation_ru_cn", "active_answer",
}
PINYIN_ALLOWED = re.compile(r"^[A-Za-zÀ-ɏÜüVv:\s'’\-.,!?，。！？“”0-9]+$")
TONE_MARK = re.compile(r"[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜĀÁǍÀĒÉĚÈĪÍǏÌŌÓǑÒŪÚǓÙǕǗǙǛ]")


def flatten(data: dict) -> tuple[list[dict], list[dict], list[dict]]:
    units, lessons, words = [], [], []
    for level in data.get("levels", []):
        for unit in level.get("units", []):
            units.append(unit)
            for lesson in unit.get("lessons", []):
                lessons.append(lesson)
                words.extend(lesson.get("vocabulary", []))
    return units, lessons, words


def validate(data: dict) -> dict:
    errors, warnings = [], []
    units, lessons, words = flatten(data)
    ids = [x.get("id") for x in [*data.get("levels", []), *units, *lessons, *words]]
    duplicates = [x for x, n in Counter(ids).items() if x and n > 1]
    if duplicates:
        errors.append(f"Неуникальные id: {duplicates[:12]}")
    lesson_by_id = {x.get("id"): x for x in lessons}
    grammar_items = [x["grammar"] for x in lessons if x.get("grammar")]
    grammar_by_id = {x.get("id"): x for x in grammar_items}
    if len(grammar_items) != len(grammar_by_id):
        errors.append("Есть повторяющиеся grammar.id")

    prior_order = -1
    seen_numbers = defaultdict(list)
    level_words = defaultdict(list)
    for lesson in lessons:
        missing = sorted(REQUIRED_LESSON - set(lesson))
        if missing:
            errors.append(f"{lesson.get('id')}: нет полей {', '.join(missing)}")
        if lesson.get("order", 0) <= prior_order:
            errors.append(f"{lesson.get('id')}: нарушен глобальный порядок")
        prior_order = lesson.get("order", 0)
        level = int(lesson.get("hsk_level", 0))
        seen_numbers[level].append(lesson.get("number"))
        count = len(lesson.get("vocabulary", []))
        if lesson.get("type") == "lesson" and not 7 <= count <= 10:
            errors.append(f"{lesson.get('id')}: {count} новых слов вместо 7–10")
        if lesson.get("type") == "review" and count:
            errors.append(f"{lesson.get('id')}: контрольный урок вводит новые слова")
        exercise_keys = set(lesson.get("exercises", {}))
        if exercise_keys != REQUIRED_EXERCISES:
            errors.append(f"{lesson.get('id')}: неполный набор типов упражнений")
        for word in lesson.get("vocabulary", []):
            level_words[level].append(word)
            for field in ("id", "hanzi", "pinyin", "translation_ru", "example"):
                if not word.get(field):
                    errors.append(f"{lesson.get('id')}: у слова нет {field}")
            pinyin = str(word.get("pinyin", ""))
            if not PINYIN_ALLOWED.fullmatch(pinyin):
                errors.append(f"{word.get('id')}: недопустимый символ в пиньине {pinyin!r}")
            if not (TONE_MARK.search(pinyin) or re.search(r"[1-5]", pinyin) or pinyin.lower() in {"de", "le", "ma", "ne", "ba", "zhe", "a", "ya"}):
                warnings.append(f"{word.get('id')}: пиньинь без явного тона {pinyin!r}")
        for family in ("listening", "comprehension", "choice"):
            for item in lesson.get("exercises", {}).get(family, []):
                options = item.get("options", [])
                if options and len(options) != len(set(options)):
                    errors.append(f"{lesson.get('id')}/{family}: одинаковые варианты")
                if options and item.get("answer") not in options:
                    errors.append(f"{lesson.get('id')}/{family}: ответ отсутствует среди вариантов")

    for level, numbers in seen_numbers.items():
        if numbers != list(range(1, len(numbers) + 1)):
            errors.append(f"HSK {level}: номера уроков идут непоследовательно")
        hanzi = [x["hanzi"] for x in level_words[level]]
        dup = [
            value for value, n in Counter(hanzi).items()
            if n > 1 and any(not x.get("duplicate_reason") for x in level_words[level] if x["hanzi"] == value)
        ]
        if dup:
            errors.append(f"HSK {level}: повторная новая лексика {dup[:12]}")
        if len(hanzi) != EXPECTED_WORDS[level]:
            errors.append(f"HSK {level}: покрыто {len(hanzi)}, ожидается {EXPECTED_WORDS[level]}")

    graph = defaultdict(list)
    grammar_order = {x["id"]: i for i, x in enumerate(grammar_items)}
    for grammar in grammar_items:
        gid = grammar["id"]
        for prereq in grammar.get("prerequisites", []):
            if prereq not in grammar_by_id:
                errors.append(f"{gid}: отсутствует prerequisite {prereq}")
            elif grammar_order[prereq] >= grammar_order[gid]:
                errors.append(f"{gid}: prerequisite {prereq} расположен не раньше")
            graph[gid].append(prereq)

    visiting, visited = set(), set()
    def walk(node: str) -> None:
        if node in visiting:
            errors.append(f"Цикл грамматики в {node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for nxt in graph[node]:
            walk(nxt)
        visiting.remove(node)
        visited.add(node)
    for node in grammar_by_id:
        walk(node)

    coverage = {}
    for level in range(1, 5):
        level_lessons = [x for x in lessons if x.get("hsk_level") == level]
        lexical = [x for x in level_lessons if x.get("type") == "lesson"]
        coverage[str(level)] = {
            "units": sum(1 for u in units if u["id"].startswith(f"h{level}-")),
            "lessons": len(level_lessons), "lexical_lessons": len(lexical),
            "review_lessons": len(level_lessons) - len(lexical),
            "target_words": EXPECTED_WORDS[level], "covered_words": len(level_words[level]),
            "word_coverage_percent": round(len(level_words[level]) / EXPECTED_WORDS[level] * 100, 1),
            "grammar_constructions": sum(1 for x in lexical if x.get("grammar")),
        }
    return {
        "ok": not errors, "errors": errors, "warnings": warnings,
        "summary": {
            "levels": len(data.get("levels", [])), "units": len(units), "lessons": len(lessons),
            "lexical_lessons": sum(x.get("type") == "lesson" for x in lessons),
            "review_lessons": sum(x.get("type") == "review" for x in lessons),
            "words": len(words), "grammar_constructions": len(grammar_items),
        },
        "coverage": coverage,
    }


def markdown(report: dict) -> str:
    s = report["summary"]
    rows = ["| Уровень | Разделы | Уроки | Контрольные | Слова | Покрытие | Грамматика |", "|---|---:|---:|---:|---:|---:|---:|"]
    for level, item in report["coverage"].items():
        rows.append(f"| HSK {level} | {item['units']} | {item['lessons']} | {item['review_lessons']} | {item['covered_words']} / {item['target_words']} | {item['word_coverage_percent']}% | {item['grammar_constructions']} |")
    status = "ПРОЙДЕН" if report["ok"] else "НЕ ПРОЙДЕН"
    return "\n".join([
        "# Отчёт покрытия Curriculum 1.0", "", f"**Валидатор: {status}.**", "",
        f"Всего: {s['levels']} уровня, {s['units']} разделов, {s['lessons']} уроков "
        f"({s['lexical_lessons']} учебных + {s['review_lessons']} контрольных), "
        f"{s['words']} слов, {s['grammar_constructions']} грамматических конструкций.", "", *rows, "",
        f"Ошибок: {len(report['errors'])}. Предупреждений: {len(report['warnings'])}.", "",
        *(f"- {x}" for x in report["errors"]),
    ]) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="curriculum/curriculum-v1.json")
    parser.add_argument("--json-report", default="curriculum/coverage-report.json")
    parser.add_argument("--md-report", default="curriculum/COVERAGE.md")
    args = parser.parse_args()
    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    report = validate(data)
    Path(args.json_report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md_report).write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"errors={len(report['errors'])} warnings={len(report['warnings'])}")
    if not report["ok"]:
        for error in report["errors"]:
            print("ERROR:", error)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
