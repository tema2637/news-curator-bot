import os, unittest
from curator.db import init_db, save_article, get_unreported_high_signal, record_user_vote, mark_articles_delivered
from curator.digest import build_digest_posts
from curator.evaluator import calculate_score

TEST_E2E_DB = "test_e2e.db"

class TestEndToEndFlow(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_E2E_DB):
            os.remove(TEST_E2E_DB)
        init_db(TEST_E2E_DB)

    def tearDown(self):
        if os.path.exists(TEST_E2E_DB):
            os.remove(TEST_E2E_DB)

    def test_full_pipeline_flow(self):
        # 1. Crawled item arrives
        raw_item = {
            "id": "gh_ollama_ollama_v05",
            "title": "[Ollama] v0.5 released with vision and tools support",
            "url": "https://github.com/ollama/ollama/releases/tag/v0.5",
            "source": "github"
        }

        # 2. Evaluation
        metrics = {"signal": 0.9, "fact": 0.95, "hype": 0.1, "category": "tools", "topics": ["ollama", "tools"]}
        weights = {"tools": 1.2, "ollama": 1.3}
        score, matched = calculate_score(raw_item["title"], metrics, weights)
        self.assertGreater(score, 0.5)

        # 3. Save with summary
        raw_item.update(metrics)
        raw_item["score"] = score
        raw_item["summary"] = (
            "🛠 **OLLAMA V0.5 — ПОДДЕРЖКА VISION И TOOL CALLING**\n\n"
            "[Ollama v0.5](https://github.com/ollama/ollama/releases/tag/v0.5) — крупный релиз локального AI-рантайма.\n\n"
            "🟢 Поддержка мультимодальных моделей Llama 3.2 Vision\n\n"
            "🔥 В итоге: запуск vision моделей на локальном GPU."
        )
        save_article(raw_item, TEST_E2E_DB)

        # 4. Digest compilation
        candidates = get_unreported_high_signal(min_score=0.25, db_path=TEST_E2E_DB)
        self.assertEqual(len(candidates), 1)

        posts = build_digest_posts(candidates, greeting="Тестовая сводка")
        # 1 banner + 1 post
        self.assertEqual(len(posts), 2)
        post_text, button_grid = posts[1]
        self.assertIn("OLLAMA V0.5", post_text)

        # 5. User voting
        cb_data = button_grid[0][0]["data"] # "v:1:gh_ollama_ollama_v05"
        self.assertTrue(cb_data.startswith("v:1:"))
        v_parts = cb_data.split(":")
        v_dir = int(v_parts[1])
        v_id = v_parts[2]

        title, adjusted = record_user_vote(v_id, v_dir, TEST_E2E_DB)
        self.assertIn("Ollama", title)

        # 6. Mark delivered
        mark_articles_delivered([c["id"] for c in candidates], TEST_E2E_DB)
        remaining = get_unreported_high_signal(min_score=0.25, db_path=TEST_E2E_DB)
        self.assertEqual(len(remaining), 0)

if __name__ == "__main__":
    unittest.main()
