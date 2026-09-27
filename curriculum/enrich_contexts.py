#!/usr/bin/env python3
"""Attach natural, graded sentence contexts to Curriculum lessons.

The source dataset is not used at runtime.  This release tool selects a small
CC-BY-SA subset, removes the English glosses, and stores only Chinese, pinyin,
token boundaries and references needed by the exercise engine.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


SOURCE_NAME = "no7z/hsk-sentences-audio"
SOURCE_REPOSITORY = "https://github.com/no7z/hsk-sentences-audio"
SOURCE_LICENSE = "CC-BY-SA-4.0"

PREFERRED_TOPICS = {
    "h1-u1": {"greetings", "identity"},
    "h1-u2": {"family", "numbers"},
    "h1-u3": {"time", "daily_actions"},
    "h1-u4": {"food", "location"},
    "h1-u5": {"transport", "weather_state"},
    "h2-u1": {"transport", "time", "daily_actions"},
    "h2-u2": {"shopping", "objects_misc"},
    "h2-u3": {"location", "transport", "objects_misc"},
    "h2-u4": {"identity", "feelings", "numbers"},
    "h2-u5": {"sports_leisure", "daily_actions", "time"},
    "h3-u1": {"daily_actions", "transport", "location"},
    "h3-u2": {"identity", "family", "feelings"},
    "h3-u3": {"shopping", "objects_misc", "feelings"},
    "h3-u4": {"daily_actions", "transport", "sports_leisure"},
    "h3-u5": {"questions", "feelings", "school_work"},
    "h4-u1": {"feelings", "school_work", "identity"},
    "h4-u2": {"shopping", "health_body", "food"},
    "h4-u3": {"feelings", "sports_leisure", "nature"},
    "h4-u4": {"school_work", "family", "nature"},
    "h4-u5": {"nature", "transport", "weather_state"},
}


def lexical_lessons(data: dict) -> list[dict]:
    return [
        lesson
        for level in data.get("levels", [])
        for unit in level.get("units", [])
        for lesson in unit.get("lessons", [])
        if lesson.get("type") == "lesson"
    ]


def all_lessons(data: dict) -> list[dict]:
    return [
        lesson
        for level in data.get("levels", [])
        for unit in level.get("units", [])
        for lesson in unit.get("lessons", [])
    ]


def rebuild_compatibility_fields(lesson: dict) -> None:
    """Keep pre-1.1 clients useful instead of serving carrier-sentence drills."""
    contexts = lesson.get("contexts", [])
    vocabulary = lesson.get("vocabulary", [])
    if len(contexts) < 3 or not vocabulary:
        return
    word_by_id = {word["id"]: word for word in vocabulary}

    def focus(context: dict) -> dict:
        return word_by_id[context["focus_word_id"]]

    def options(answer: str, field: str) -> list[str]:
        values = [answer]
        for word in vocabulary:
            value = word.get(field)
            if value and value not in values:
                values.append(value)
        return values[:4]

    first, second, third = contexts
    first_word, second_word = focus(first), focus(second)
    lesson["examples"] = [{
        "cn": context["chinese"],
        "pinyin": context["pinyin"],
        "ru": f"Ключевое слово: «{focus(context)['hanzi']}» — {focus(context)['translation_ru']}.",
    } for context in contexts]
    lesson["dialogue"] = {
        "cn": f"{first['chinese']}\n{second['chinese']}",
        "pinyin": f"{first['pinyin']}\n{second['pinyin']}",
        "ru": "Два естественных контекста с новой лексикой урока.",
    }
    lesson["exercises"] = {
        "listening": [{
            "audio_text": first["chinese"],
            "question_ru": "Какое новое слово прозвучало в естественной фразе?",
            "options": options(first_word["hanzi"], "hanzi"),
            "answer": first_word["hanzi"],
            "pinyin": first["pinyin"],
        }],
        "comprehension": [{
            "text_cn": second["chinese"], "text_pinyin": second["pinyin"],
            "question_ru": f"Что означает «{second_word['hanzi']}» в этой фразе?",
            "options": options(second_word["translation_ru"], "translation_ru"),
            "answer": second_word["translation_ru"],
        }],
        "reading": [{
            "text_cn": second["chinese"], "text_pinyin": second["pinyin"],
            "question_ru": "Какое новое слово используется в контексте?",
            "answer": second_word["hanzi"],
        }],
        "choice": [{
            "question_ru": second_word["translation_ru"],
            "options": options(second_word["hanzi"], "hanzi"),
            "answer": second_word["hanzi"],
        }],
        "word_order": [{
            "tokens": third["tokens"], "answer": third["chinese"], "pinyin": third["pinyin"],
        }],
        "fill_blank": [{
            "sentence": second["chinese"].replace(second_word["hanzi"], "___", 1),
            "answer": second_word["hanzi"], "pinyin": second["pinyin"],
        }],
        "translation_ru_cn": [{
            "prompt_ru": second_word["translation_ru"],
            "answers": [second_word["hanzi"]], "pinyin": second_word["pinyin"],
        }],
        "active_answer": [{
            "prompt_ru": f"Восстановите китайскую фразу по пиньиню: {first['pinyin']}",
            "sample_cn": first["chinese"], "sample_pinyin": first["pinyin"],
        }],
    }


def enrich(data: dict, sentences: list[dict], source_commit: str) -> dict:
    index: dict[str, list[dict]] = defaultdict(list)
    for sentence in sentences:
        for token in {item.get("word") for item in sentence.get("tokens", []) if item.get("word")}:
            index[token].append(sentence)

    cumulative_words: set[str] = set()
    selected_source_ids: set[str] = set()
    for lesson in lexical_lessons(data):
        vocabulary = lesson.get("vocabulary", [])
        word_by_hanzi = {word["hanzi"]: word for word in vocabulary}
        lesson_words = set(word_by_hanzi)
        cumulative_words.update(lesson_words)
        preferred = PREFERRED_TOPICS.get(lesson.get("unit_id"), set())
        candidate_by_id: dict[str, dict] = {}
        for hanzi in lesson_words:
            for sentence in index.get(hanzi, []):
                if int(sentence.get("hsk_level", 99)) <= int(lesson["hsk_level"]):
                    candidate_by_id[sentence["id"]] = sentence

        def rank(sentence: dict) -> tuple:
            tokens = [item["word"] for item in sentence.get("tokens", [])]
            token_set = set(tokens)
            covered = lesson_words & token_set
            unknown = token_set - cumulative_words
            return (
                len(covered),
                int(sentence.get("topic") in preferred),
                -len(unknown),
                -abs(len(tokens) - 7),
                -len(sentence.get("chinese", "")),
                sentence.get("id", ""),
            )

        candidates = sorted(candidate_by_id.values(), key=rank, reverse=True)

        for word in vocabulary:
            example_pool = index.get(word["hanzi"], []) or [
                sentence for sentence in sentences if word["hanzi"] in sentence.get("chinese", "")
            ]
            graded_examples = [
                sentence for sentence in example_pool
                if int(sentence.get("hsk_level", 99)) <= int(lesson["hsk_level"])
            ]
            examples = graded_examples or list(example_pool)
            if not examples:
                word["example"] = {
                    "cn": word["hanzi"], "pinyin": word["pinyin"], "ru": word["translation_ru"],
                }
                continue
            example = sorted(examples, key=rank, reverse=True)[0]
            word["example"] = {
                "cn": example["chinese"],
                "pinyin": example["pinyin"],
                "ru": f"Контекст употребления: «{word['hanzi']}» — {word['translation_ru']}.",
                "source_sentence_id": example["id"],
            }

        chosen: list[tuple[dict, str]] = []
        used_focus: set[str] = set()
        used_chinese: set[str] = set()

        for require_new_focus in (True, False):
            for sentence in candidates:
                if len(chosen) >= 3:
                    break
                if sentence.get("chinese") in used_chinese:
                    continue
                token_words = [item["word"] for item in sentence.get("tokens", [])]
                focus_candidates = [word["hanzi"] for word in vocabulary if word["hanzi"] in token_words]
                if require_new_focus:
                    focus_candidates = [hanzi for hanzi in focus_candidates if hanzi not in used_focus]
                if not focus_candidates:
                    continue
                focus = focus_candidates[0]
                chosen.append((sentence, focus))
                used_focus.add(focus)
                used_chinese.add(sentence["chinese"])

        if len(chosen) < 3:
            raise ValueError(f"{lesson['id']}: found only {len(chosen)} usable natural contexts")

        contexts = []
        for sentence, focus in chosen:
            focus_word = word_by_hanzi[focus]
            tokens = [item["word"] for item in sentence.get("tokens", [])]
            contexts.append({
                "source_sentence_id": sentence["id"],
                "chinese": sentence["chinese"],
                "pinyin": sentence["pinyin"],
                "sentence_type": sentence.get("sentence_type", "statement"),
                "topic": sentence.get("topic", "misc"),
                "tokens": tokens,
                "focus_word_id": focus_word["id"],
                "focus_hanzi": focus_word["hanzi"],
                "focus_pinyin": focus_word["pinyin"],
                "focus_translation_ru": focus_word["translation_ru"],
                "lesson_word_ids": [word_by_hanzi[token]["id"] for token in tokens if token in word_by_hanzi],
            })
            selected_source_ids.add(sentence["id"])
        lesson["exercise_version"] = 2
        lesson["contexts"] = contexts
        rebuild_compatibility_fields(lesson)

    for lesson in all_lessons(data):
        lesson["exercise_version"] = 2

    data["version"] = "1.1.0"
    data["exercise_version"] = 2
    data["context_source"] = {
        "name": SOURCE_NAME,
        "repository": SOURCE_REPOSITORY,
        "commit": source_commit,
        "license": SOURCE_LICENSE,
        "selected_sentences": len(selected_source_ids),
        "note_ru": "Выбранные китайские предложения и пиньинь используются как естественный контекст упражнений.",
    }
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curriculum", default="curriculum/curriculum-v1.json")
    parser.add_argument("--sentences", required=True, help="Path to no7z/hsk-sentences-audio dist/sentences.json")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    path = Path(args.curriculum)
    data = json.loads(path.read_text(encoding="utf-8"))
    sentences = json.loads(Path(args.sentences).read_text(encoding="utf-8"))
    enriched = enrich(data, sentences, args.source_commit)
    output = Path(args.output or args.curriculum)
    output.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "lessons": len(lexical_lessons(enriched)),
        "contexts": sum(len(lesson.get("contexts", [])) for lesson in lexical_lessons(enriched)),
        "source_sentences": enriched["context_source"]["selected_sentences"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
