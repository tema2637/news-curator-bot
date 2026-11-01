import unittest
from news_daemon import parse_allowed_users
from curator.digest import build_digest, build_digest_posts

class TestAuthAndAsync(unittest.TestCase):
    def test_parse_allowed_users_valid(self):
        self.assertEqual(parse_allowed_users("12345, 67890"), {12345, 67890})
        self.assertEqual(parse_allowed_users("12345"), {12345})

    def test_parse_allowed_users_edge_cases(self):
        # Empty string with fallback
        self.assertEqual(parse_allowed_users("", fallback=999), {999})
        # None with fallback
        self.assertEqual(parse_allowed_users(None, fallback=888), {888})
        # Empty string without fallback
        self.assertEqual(parse_allowed_users(""), set())
        # Whitespace and trailing commas
        self.assertEqual(parse_allowed_users("  123 ,  , 456 ,  "), {123, 456})
        # Invalid / non-numeric tokens ignored
        self.assertEqual(parse_allowed_users("123, invalid, abc, 456"), {123, 456})

    def test_build_digest_posts_is_pure_data(self):
        articles = [
            {"id": "a1", "title": "Model Release", "url": "https://example.com/1", "summary": "Summary 1"},
            {"id": "a2", "title": "Tool Release", "url": "https://example.com/2", "summary": "Summary 2"}
        ]
        # Should return list of (text, button_grid) without making network calls
        posts = build_digest_posts(articles, greeting="Test Greeting")
        self.assertIsInstance(posts, list)
        self.assertEqual(len(posts), 3) # banner + 2 posts
        text, buttons = posts[0]
        self.assertIn("Test Greeting", text)

    def test_build_digest_single_is_pure_data(self):
        articles = [
            {"id": "a1", "title": "Model Release", "url": "https://example.com/1", "summary": "Summary 1"}
        ]
        text, buttons = build_digest(articles, greeting="Single Digest")
        self.assertIsInstance(text, str)
        self.assertIn("Single Digest", text)
        self.assertIsInstance(buttons, list)

if __name__ == "__main__":
    unittest.main()
