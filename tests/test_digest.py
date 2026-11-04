import unittest
from curator.digest import build_digest, build_digest_posts, format_single_post

class TestDigest(unittest.TestCase):
    def test_format_single_post(self):
        item = {
            "id": "gh_kandinsky",
            "title": "Kandinsky 5.0",
            "url": "https://github.com/kandinskylab/kandinsky-5",
            "summary": "🎬 **KANDINSKY 5.0**\n\n[Kandinsky 5.0](https://github.com/kandinskylab/kandinsky-5) — релиз.\n\n🟢 19B параметров\n\n🔥 В итоге: топ для ComfyUI.\n\n#AI",
            "user_vote": 0
        }
        text, buttons = format_single_post(item)
        self.assertIn("🎬 **KANDINSKY 5.0**", text)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0]["text"], "👍 Полезно")
        self.assertEqual(buttons[0][1]["text"], "👎 Шум")

    def test_build_digest_posts(self):
        items = [
            {"id": "item1", "title": "Free API Gateway", "url": "https://api.com", "summary": "⚡ **FREE API**", "user_vote": 0},
            {"id": "item2", "title": "Fast Docker Runtime", "url": "https://docker.com", "summary": "🛠 **DOCKER**", "user_vote": 1}
        ]
        posts = build_digest_posts(items, greeting="Утренний дайджест")
        # 1 banner post + 2 item posts = 3 posts
        self.assertEqual(len(posts), 3)
        self.assertIn("Утренний дайджест", posts[0][0])
        self.assertIn("FREE API", posts[1][0])
        self.assertIn("DOCKER", posts[2][0])

    def test_build_empty_digest(self):
        posts = build_digest_posts([], greeting="Сводка")
        self.assertEqual(len(posts), 1)
        self.assertIn("не найдено", posts[0][0])

    def test_build_single_digest(self):
        items = [
            {
                "id": "it1",
                "title": "llama.cpp b11785",
                "url": "https://github.com/ggml-org/llama.cpp/releases/tag/b11785",
                "summary": "🧠 **LLAMA.CPP**\n\n[llama.cpp](https://github.com/ggml-org/llama.cpp) — релиз.\n\n🟢 Улучшен MoE-расчет\n\n🟢 Исправлен оверфлоу\n\n🔥 В итоге: супер.",
                "user_vote": 1
            },
            {
                "id": "it2",
                "title": "MiniMax Flash",
                "url": "https://minimax.io",
                "summary": "⚡ **MINIMAX**\n\n[MiniMax](https://minimax.io) — модель.\n\n🟢 Низкая латентность\n\n🔥 В итоге: дешевые токены.",
                "user_vote": 0
            }
        ]
        text, grid = build_digest(items, greeting="Сводка дня")
        self.assertIn("Сводка дня", text)
        self.assertIn("1️⃣ **[llama.cpp](https://github.com/ggml-org/llama.cpp)**", text)
        self.assertIn("2️⃣ **[MiniMax](https://minimax.io)**", text)
        self.assertIn("Улучшен MoE-расчет", text)
        self.assertEqual(len(grid), 3)
        # Check first row has upvotes with checkmark for voted item
        self.assertEqual(grid[0][0]["text"], "✓ 1")
        self.assertEqual(grid[0][1]["text"], "👍 2")
        # Check third row has recap button
        self.assertEqual(grid[2][0]["data"], "cmd:recap")
        self.assertIn("Объединить", grid[2][0]["text"])

    def test_generate_digest_recap_fallback(self):
        from unittest.mock import patch
        from curator.summarizer import generate_digest_recap
        empty_res = generate_digest_recap([])
        self.assertIn("нет новостей", empty_res)

        items = [
            {"title": "llama.cpp b11785", "url": "https://github.com/ggml-org/llama.cpp", "summary": "⚡ Ускорение"}
        ]
        with patch("curator.multi_agent.run_four_agent_recap_pipeline", return_value="📊 **КРАТКАЯ СПРАВКА ПО ПОДБОРКЕ**\n\n• [llama.cpp](https://github.com/ggml-org/llama.cpp) — Ускорение"):
            res = generate_digest_recap(items)
            self.assertIn("СПРАВКА", res)
            self.assertIn("llama.cpp", res)

if __name__ == "__main__":
    unittest.main()
