import unittest

from domain.voice.text_processor import TextProcessor


class TestTextProcessor(unittest.TestCase):
    def setUp(self):
        self.tp = TextProcessor()

    def test_remove_chinese_phrase_repetition(self):
        text = "嗯，这是这是第二个。"
        processed, meta = self.tp.post_process_text(text, remove_repetitions=True, profanity_words=None)
        self.assertTrue(meta["removed_repetitions"])
        self.assertEqual(processed, "嗯，这是第二个。")

    def test_remove_english_word_repetition(self):
        text = "starting from the the first day in the world"
        processed, meta = self.tp.post_process_text(text, remove_repetitions=True, profanity_words=None)
        self.assertTrue(meta["removed_repetitions"])
        self.assertEqual(processed, "starting from the first day in the world")

    def test_profanity_mask(self):
        text = "这句话包含坏词，坏词不应该出现。"
        processed, meta = self.tp.post_process_text(
            text,
            remove_repetitions=False,
            profanity_words=["坏词"],
            profanity_action="mask",
            profanity_mask_char="*",
        )
        self.assertTrue(meta["profanity_hit"])
        self.assertIn("**", processed)

    def test_profanity_replace(self):
        text = "你这个坏词！"
        processed, meta = self.tp.post_process_text(
            text,
            remove_repetitions=False,
            profanity_words=["坏词"],
            profanity_action="replace",
            profanity_replacement="[已处理]",
        )
        self.assertTrue(meta["profanity_hit"])
        self.assertIn("[已处理]", processed)

    def test_profanity_regex_rule(self):
        text = "n m s l 这种变体也要能命中"
        processed, meta = self.tp.post_process_text(
            text,
            remove_repetitions=False,
            profanity_words=[r"/n\s*m\s*s\s*l/i"],
            profanity_action="mask",
            profanity_mask_char="*",
        )
        self.assertTrue(meta["profanity_hit"])
        self.assertNotIn("n m s l", processed.lower())

    def test_profanity_in_words_cross_word(self):
        # 模拟字级 words（常见于 timestamp->char 映射）
        words = [
            {"text": "你", "start": 0.0, "end": 0.1},
            {"text": "妈", "start": 0.1, "end": 0.2},
            {"text": "的", "start": 0.2, "end": 0.3},
            {"text": "好", "start": 0.3, "end": 0.4},
        ]
        new_words, hit = self.tp.filter_profanity_in_words(
            words,
            profanity_words=["你妈的"],
            action="mask",
            mask_char="*",
            match_mode="substring",
        )
        self.assertTrue(hit)
        self.assertEqual("".join(w["text"] for w in new_words), "***好")

    def test_repetition_in_words_chinese_phrase(self):
        words = [{"text": t, "start": 0.0, "end": 0.0} for t in list("这是这是第二个")]
        new_words, changed = self.tp.remove_repetitions_in_words(words)
        self.assertTrue(changed)
        self.assertEqual("".join(w["text"] for w in new_words), "这是第二个")

    def test_repetition_in_words_english_the_the(self):
        words = [
            {"text": "the", "start": 0.0, "end": 0.1},
            {"text": " ", "start": 0.1, "end": 0.11},
            {"text": "the", "start": 0.11, "end": 0.2},
        ]
        new_words, changed = self.tp.remove_repetitions_in_words(words)
        self.assertTrue(changed)
        self.assertEqual("".join(w["text"] for w in new_words), "the")

    def test_repetition_in_words_fillers(self):
        words = [{"text": t, "start": 0.0, "end": 0.0} for t in list("嗯嗯嗯我们开始")]
        new_words, changed = self.tp.remove_repetitions_in_words(words)
        self.assertTrue(changed)
        self.assertEqual("".join(w["text"] for w in new_words), "嗯我们开始")

    def test_tail_only_change(self):
        self.assertTrue(self.tp.is_tail_only_change("你好，", "你好。"))
        self.assertTrue(self.tp.is_tail_only_change("你好", "你好。"))
        self.assertFalse(self.tp.is_tail_only_change("这是这是第二个。", "这是第二个。"))


if __name__ == "__main__":
    unittest.main()

