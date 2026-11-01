import os, unittest
from curator.db import (
    init_db,
    save_article,
    get_unreported_high_signal,
    mark_articles_delivered,
    record_user_vote,
    get_taste_weights,
    update_taste_weight,
    get_setting,
    set_setting
)

TEST_DB = "test_curator.db"

class TestDB(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        init_db(TEST_DB)

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_save_and_retrieve_articles(self):
        art = {
            "id": "hn_100", "title": "PyTorch 2.5", "url": "https://pytorch.org",
            "source": "hn", "signal": 0.9, "fact": 0.8, "hype": 0.1, "score": 0.85,
            "category": "tools", "summary": "• PyTorch released\n• Faster RoPE"
        }
        save_article(art, TEST_DB)
        candidates = get_unreported_high_signal(min_score=0.25, db_path=TEST_DB)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "hn_100")
        self.assertEqual(candidates[0]["category"], "tools")

        # Mark delivered
        mark_articles_delivered(["hn_100"], TEST_DB)
        remaining = get_unreported_high_signal(min_score=0.25, db_path=TEST_DB)
        self.assertEqual(len(remaining), 0)

    def test_vote_adjusts_weight(self):
        art = {
            "id": "hn_200", "title": "DeepSeek v3 release", "url": "https://deepseek.com",
            "source": "hn", "signal": 0.9, "fact": 0.9, "hype": 0.1, "score": 0.9,
            "category": "models", "summary": "• New model\n• Open weights"
        }
        save_article(art, TEST_DB)
        initial_weights = get_taste_weights(TEST_DB)
        prev_w = initial_weights.get("deepseek", 1.0)

        title, adjusted = record_user_vote("hn_200", +1, TEST_DB)
        self.assertEqual(title, "DeepSeek v3 release")
        new_weights = get_taste_weights(TEST_DB)
        self.assertAlmostEqual(new_weights["deepseek"], prev_w + 0.15, places=2)

    def test_settings_storage(self):
        set_setting("lang", "en", TEST_DB)
        self.assertEqual(get_setting("lang", "ru", TEST_DB), "en")
        set_setting("digest_limit", "7", TEST_DB)
        self.assertEqual(get_setting("digest_limit", "4", TEST_DB), "7")
        set_setting("schedule_mode", "morning", TEST_DB)
        self.assertEqual(get_setting("schedule_mode", "2x", TEST_DB), "morning")
        set_setting("threshold", "0.40", TEST_DB)
        self.assertEqual(get_setting("threshold", "0.25", TEST_DB), "0.40")
        set_setting("digest_format", "single", TEST_DB)
        self.assertEqual(get_setting("digest_format", "multi", TEST_DB), "single")

if __name__ == "__main__":
    unittest.main()
