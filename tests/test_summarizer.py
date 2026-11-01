import unittest
from curator.summarizer import clean_summary_post

class TestSummarizer(unittest.TestCase):
    def test_clean_summary_post_standard(self):
        raw = (
            "🎬 **KANDINSKY 5.0 — ОТКРЫТАЯ ЛИНЕЙКА МОДЕЛЕЙ**\n\n"
            "[Kandinsky 5.0](https://github.com/kandinskylab/kandinsky-5) — семейство диффузионных моделей.\n\n"
            "🟢 Video Pro — 19B параметров для Text-to-Video.\n\n"
            "🔥 В итоге: запуск локально в ComfyUI.\n\n"
            "#AI #Kandinsky #OpenSource"
        )
        cleaned = clean_summary_post(raw, "Kandinsky 5.0", "https://github.com/kandinskylab/kandinsky-5")
        self.assertIn("🎬 **KANDINSKY 5.0", cleaned)
        self.assertIn("🟢 Video Pro", cleaned)
        self.assertIn("🔥 В итоге", cleaned)
        self.assertIn("#AI", cleaned)

    def test_clean_summary_code_fenced(self):
        raw = "```markdown\n🎬 **TITLE**\n\n[Title](https://link.com) — desc\n\n🟢 Feature\n\n🔥 В итоге: вывод\n\n#AI\n```"
        cleaned = clean_summary_post(raw, "Title", "https://link.com")
        self.assertFalse(cleaned.startswith("```"))
        self.assertFalse(cleaned.endswith("```"))

    def test_clean_summary_fallback_on_empty(self):
        cleaned = clean_summary_post("", "New Model", "https://example.com/model")
        self.assertIn("[New Model](https://example.com/model)", cleaned)
        self.assertIn("• Под капотом:", cleaned)
        self.assertIn("🔥 Итог:", cleaned)

    def test_clean_summary_removes_ai_slop(self):
        raw = (
            "🛠 **TOOL**\n\n[Tool](https://t.com) меняет правила игры в современном мире.\n\n"
            "🟢 Это настоящий подарок для разработчиков и впечатляющие результаты.\n\n"
            "🔥 В итоге: не упустите шанс."
        )
        cleaned = clean_summary_post(raw, "Tool", "https://t.com")
        self.assertNotIn("меняет правила игры", cleaned)
        self.assertNotIn("в современном мире", cleaned)
        self.assertNotIn("настоящий подарок для разработчиков", cleaned)
        self.assertNotIn("впечатляющие результаты", cleaned)
        self.assertNotIn("не упустите шанс", cleaned)


    def test_clean_summary_cleans_protocol_duplication(self):
        raw = "⚡️ [Tool](https://https://github.com/repo) — desc\n\n• Под капотом: info\n\n🔥 Итог: ok"
        cleaned = clean_summary_post(raw, "Tool", "https://github.com/repo")
        self.assertNotIn("https://https://", cleaned)
        self.assertIn("https://github.com/repo", cleaned)


if __name__ == "__main__":
    unittest.main()
