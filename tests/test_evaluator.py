import unittest
from curator.evaluator import calculate_score, parse_classification_json

class TestEvaluator(unittest.TestCase):
    def test_parse_clean_json(self):
        raw = '{"signal": 0.8, "fact": 0.9, "hype": 0.2, "category": "tools", "topics": ["python"]}'
        parsed = parse_classification_json(raw)
        self.assertEqual(parsed["category"], "tools")
        self.assertEqual(parsed["signal"], 0.8)
        self.assertEqual(parsed["fact"], 0.9)
        self.assertEqual(parsed["hype"], 0.2)
        self.assertEqual(parsed["topics"], ["python"])

    def test_parse_code_fenced_json(self):
        raw = '```json\n{"signal": 0.7, "fact": 0.8, "hype": 0.1, "category": "free_api", "topics": ["api"]}\n```'
        parsed = parse_classification_json(raw)
        self.assertEqual(parsed["category"], "free_api")
        self.assertEqual(parsed["signal"], 0.7)

    def test_parse_fallback_on_corrupt(self):
        raw = 'Not JSON at all'
        parsed = parse_classification_json(raw)
        self.assertIn("category", parsed)
        self.assertIn("signal", parsed)
        self.assertEqual(parsed["category"], "other")
        self.assertEqual(parsed["signal"], 0.0)

    def test_calculate_score_formula(self):
        metrics = {"signal": 0.8, "fact": 0.6, "hype": 0.2, "category": "models"}
        weights = {"deepseek": 1.5}
        score, matched = calculate_score("DeepSeek-V3 weights released", metrics, weights)
        # base = (0.8 * 0.6) + (0.6 * 0.4) - (0.2 * 0.3) = 0.48 + 0.24 - 0.06 = 0.66
        # mult = 1.5 -> 0.99
        self.assertAlmostEqual(score, 0.99, places=2)
        self.assertIn("deepseek", matched)

    def test_irrelevant_category_filtered_out(self):
        metrics = {"signal": 0.9, "fact": 0.9, "hype": 0.1, "category": "other"}
        score, matched = calculate_score("General news headline", metrics, {})
        self.assertEqual(score, 0.0)

    def test_category_normalization(self):
        raw = '{"signal": 0.5, "fact": 0.5, "hype": 0.5, "category": "random_stuff"}'
        parsed = parse_classification_json(raw)
        self.assertEqual(parsed["category"], "other")
        self.assertEqual(parsed["signal"], 0.0)

    def test_blacklist_filters_out_headline(self):
        metrics = {"signal": 0.9, "fact": 0.9, "hype": 0.1, "category": "tools"}
        score, matched = calculate_score("New crypto trading bot", metrics, {}, blacklist={"crypto", "nft"})
        self.assertEqual(score, 0.0)
        self.assertIn("blacklist:crypto", matched)

    def test_active_topics_filter(self):
        metrics = {"signal": 0.9, "fact": 0.9, "hype": 0.1, "category": "models"}
        # If models is active, passes
        score, _ = calculate_score("Qwen 2.5 open weights", metrics, {}, active_topics={"models"})
        self.assertGreater(score, 0.5)

        # If only free_api is active and no subtopic matches, filtered out
        score2, _ = calculate_score("Ancient historical story", metrics, {}, active_topics={"free_api"})
        self.assertEqual(score2, 0.0)

    def test_json_with_nested_curly_braces_in_strings(self):
        raw = 'Here is the result: {"category": "models", "signal": 0.85, "fact": 0.9, "hype": 0.1, "topics": ["use {curly} brackets in {nested} form"]} extra text {another: 1}'
        parsed = parse_classification_json(raw)
        self.assertEqual(parsed["category"], "models")
        self.assertEqual(parsed["signal"], 0.85)
        self.assertEqual(parsed["topics"], ["use {curly} brackets in {nested} form"])

    def test_json_with_escaped_quotes(self):
        raw = '```json\n{"category": "tools", "signal": 0.8, "fact": 0.8, "hype": 0.1, "topics": ["test \\"quoted\\" values"]}\n```'
        parsed = parse_classification_json(raw)
        self.assertEqual(parsed["category"], "tools")
        self.assertIn('test "quoted" values', parsed["topics"])

    def test_json_with_preamble_containing_curly_braces(self):
        raw = 'Вот пример {ключ: значение} — теперь результат: {"category": "models", "signal": 0.85, "fact": 0.9, "hype": 0.1, "topics": ["test"]}'
        parsed = parse_classification_json(raw)
        self.assertEqual(parsed["category"], "models")
        self.assertEqual(parsed["signal"], 0.85)
        self.assertIn("test", parsed["topics"])

    def test_is_empty_bump_filtering(self):
        from curator.evaluator import is_empty_bump, classify_article
        # Empty bumps should be detected
        self.assertTrue(is_empty_bump("[SGLang] v0.5.23", "Bump version"))
        self.assertTrue(is_empty_bump("v1.2.3", ""))
        self.assertTrue(is_empty_bump("Release b11780", "no functional changes"))

        # Releases with meaningful changes should pass
        self.assertFalse(is_empty_bump("Ollama v0.40.9-rc0", "Fixed CUDA memory leak and added FlashAttention"))
        self.assertFalse(is_empty_bump("DeepSeek-V3", "Weights released"))

        # classify_article rejects empty bump with signal 0.0
        m = classify_article("[SGLang] v0.5.23", source="github", content="Bump version to 0.5.23")
        self.assertEqual(m["signal"], 0.0)
        self.assertEqual(m["category"], "other")

        # classify_article accepts release with actual changelog
        m_good = classify_article("[llama.cpp] b11792", source="github", content="Added CUDA flash attention kernel fix")
        self.assertEqual(m_good["signal"], 0.95)
        self.assertEqual(m_good["category"], "tools")

if __name__ == "__main__":
    unittest.main()
