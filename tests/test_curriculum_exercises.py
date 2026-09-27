import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CurriculumExerciseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / "curriculum" / "curriculum-v1.json").read_text(encoding="utf-8")
        cls.data = json.loads(cls.raw)
        cls.lessons = [
            lesson
            for level in cls.data["levels"]
            for unit in level["units"]
            for lesson in unit["lessons"]
            if lesson["type"] == "lesson"
        ]

    def test_every_lexical_lesson_has_three_distinct_focus_contexts(self):
        self.assertEqual(len(self.lessons), 149)
        for lesson in self.lessons:
            contexts = lesson.get("contexts", [])
            self.assertEqual(len(contexts), 3, lesson["id"])
            self.assertEqual(len({item["focus_word_id"] for item in contexts}), 3, lesson["id"])
            vocabulary_ids = {word["id"] for word in lesson["vocabulary"]}
            self.assertTrue({item["focus_word_id"] for item in contexts} <= vocabulary_ids)
            for context in contexts:
                self.assertEqual(
                    len(set(context.get("lesson_word_ids", []))), 1,
                    f"{lesson['id']}: listening prompt has more than one new lesson word",
                )

    def test_contexts_are_natural_source_material_not_carrier_templates(self):
        contexts = [item for lesson in self.lessons for item in lesson["contexts"]]
        self.assertEqual(len(contexts), 447)
        self.assertGreaterEqual(len({item["source_sentence_id"] for item in contexts}), 380)
        for item in contexts:
            self.assertNotIn("今天我们学习", item["chinese"])
            self.assertNotIn("今天学什么", item["chinese"])
            self.assertIn(item["focus_hanzi"], item["chinese"])
            self.assertTrue(item["pinyin"])
            self.assertTrue(item["tokens"])

    def test_context_provenance_is_pinned(self):
        source = self.data["context_source"]
        self.assertEqual(self.data["version"], "1.2.0")
        self.assertEqual(self.data["exercise_version"], 3)
        self.assertEqual(source["license"], "CC-BY-SA-4.0")
        self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")

    def test_no_carrier_sentences_or_unchecked_freeform_tasks_remain(self):
        self.assertNotIn("今天我们学习", self.raw)
        self.assertNotIn("今天学什么", self.raw)
        self.assertNotIn("Составьте короткую фразу", self.raw)
        examples = [word["example"] for lesson in self.lessons for word in lesson["vocabulary"]]
        self.assertGreaterEqual(sum("source_sentence_id" in item for item in examples), 1170)
        client = (ROOT / "curriculum-app.js").read_text(encoding="utf-8")
        self.assertNotIn("Получилось передать мысль", client)
        self.assertNotIn("Нужно повторить</button>", client)
        self.assertIn("Восстановите фразу по пиньиню", client)


if __name__ == "__main__":
    unittest.main()
