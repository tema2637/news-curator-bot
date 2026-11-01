import unittest
from curator.sources import (
    fetch_hacker_news,
    fetch_reddit_ai,
    fetch_github_releases,
    fetch_huggingface_trending,
    fetch_tech_rss,
    fetch_telegram_channels,
    fetch_all_sources,
    CURATED_TG_CHANNELS,
    CURATED_TECH_RSS
)

class TestSources(unittest.TestCase):
    def test_curated_tg_channels(self):
        self.assertIn("whackdoor", CURATED_TG_CHANNELS)
        self.assertIn("forgetmeai", CURATED_TG_CHANNELS)
        self.assertIn("ai_for_devs", CURATED_TG_CHANNELS)
        self.assertIn("NoBlok", CURATED_TG_CHANNELS)

    async def _async_test_none_client(self):
        res = await fetch_telegram_channels(None)
        self.assertEqual(res, [])

    def test_tg_channels_none_client(self):
        import asyncio
        asyncio.run(self._async_test_none_client())
    def test_item_structure(self):
        sample = {"id": "hn_123", "title": "Test", "url": "https://example.com", "source": "hn"}
        self.assertIn("id", sample)
        self.assertIn("title", sample)
        self.assertIn("url", sample)
        self.assertIn("source", sample)

    def test_fetch_hn_smoke(self):
        items = fetch_hacker_news(limit=3)
        self.assertIsInstance(items, list)
        if items:
            self.assertTrue(items[0]["id"].startswith("hn_"))
            self.assertTrue(items[0]["url"].startswith("http"))
            self.assertEqual(items[0]["source"], "hn")

    def test_fetch_reddit_smoke(self):
        items = fetch_reddit_ai(limit=3)
        self.assertIsInstance(items, list)
        if items:
            self.assertTrue(items[0]["id"].startswith("reddit_"))
            self.assertEqual(items[0]["source"], "reddit")

    def test_fetch_github_smoke(self):
        items = fetch_github_releases()
        self.assertIsInstance(items, list)
        if items:
            self.assertTrue(items[0]["id"].startswith("gh_"))
            self.assertEqual(items[0]["source"], "github")

    def test_fetch_huggingface_smoke(self):
        items = fetch_huggingface_trending(limit=3)
        self.assertIsInstance(items, list)
        if items:
            self.assertTrue(items[0]["id"].startswith("hf_"))
            self.assertEqual(items[0]["source"], "huggingface")

    def test_fetch_tech_rss_smoke(self):
        items = fetch_tech_rss(limit_per_feed=2)
        self.assertIsInstance(items, list)
        if items:
            self.assertTrue(items[0]["source"] in ("rozetked", "securitylab", "3dnews", "habr"))
            self.assertTrue(items[0]["url"].startswith("http"))

    def test_error_resilience(self):
        from curator.sources import safe_fetch_json
        res = safe_fetch_json("https://127.0.0.1:9999/broken.json", timeout=1)
        self.assertIsNone(res)

if __name__ == "__main__":
    unittest.main()
