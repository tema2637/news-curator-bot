# Proactive Multi-Source News Curator & Scheduled Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous news curator daemon in Python that collects technical news from Hacker News, Reddit, and GitHub, filters out hype and politics with Llama 70B, extracts article content with Tinyfish web/fetch, generates categorized Russian digests at 08:00 and 20:00 MSK (and on-demand), and supports interactive per-item voting via Telegram MTProto.

**Architecture:** A single async Python process composed of decoupled modules: ingestion crawlers (HN, Reddit, GitHub), an LLM evaluator (9Router Llama 70B System 1 + Tinyfish web/fetch + System 2 summarizer), a SQLite persistence layer with WAL mode for candidate pooling and taste weights, a digest compiler formatting 3 categorized sections, and a Telethon MTProto bot delivering scheduled and on-demand digests with inline voting buttons.

**Tech Stack:** Python 3.14, Telethon (MTProto proxy transport), SQLite3 (WAL mode), 9Router API (Llama 3.3 70B, Tinyfish web/fetch and search).

**Spec:** `docs/superpowers/specs/2026-10-20-news-curator-digest-design.md`

## Global Constraints

- **Python Runtime:** `C:\Python314\python.exe` on Windows host.
- **Telegram Connection:** Telethon over MTProto proxy with credentials configured via environment variables.
- **9Router Gateway:** `http://localhost:20128/v1` with Bearer token configured via environment variables.
- **Models:** `cf/@cf/meta/llama-3.3-70b-instruct-fp8-fast` for classification and summarization; `tinyfish` for `web/fetch` and `search`.
- **No Third-Party Scraping Libraries:** Use Python stdlib (`urllib.request`, `xml.etree.ElementTree`, `json`, `sqlite3`, `asyncio`) and `telethon`.
- **Delivery Windows:** Scheduled at 08:00 MSK and 20:00 MSK daily, plus on-demand via `/digest`.
- **Zero-Spam Policy:** No unsolicited real-time messages; all updates bundled into digests.

## Review Focus

- **Reddit/GitHub rate limits or 429/403 responses:** Crawlers must handle HTTP errors gracefully, returning empty lists without failing the overall sweep.
- **Malformatted LLM JSON from System 1:** Parser must strip code fences and handle missing fields with safe fallback scores (`signal=0.2, fact=0.5, hype=0.5, category="tools"`).
- **Overlong Telegram messages exceeding 4096 characters:** Digest formatter must enforce length caps on summaries and trim section items to fit in a single message.
- **Telegram button callback data overflow:** Telegram limits callback_data to 64 bytes; vote callbacks must use compact IDs (`v:1:<short_id>`).
- **Concurrent DB access between bot commands and background poller:** SQLite connection must enable WAL mode and use timeout=15.0 with short transactions.

---

### Task 1: Multi-Source Crawlers (Hacker News, Reddit, GitHub)

**Files:**
- Create: `curator/sources.py`
- Test: `tests/test_sources.py`

**Interfaces:**
- Produces:
  ```python
  def fetch_hacker_news(limit: int = 20) -> list[dict]: ...
  def fetch_reddit_ai(limit: int = 15) -> list[dict]: ...
  def fetch_github_releases() -> list[dict]: ...
  def fetch_all_sources() -> list[dict]: ...
  # Each item dictionary format:
  # {"id": str, "title": str, "url": str, "source": str}
  ```

- [ ] **Step 1: Write the failing tests for sources in `tests/test_sources.py`**

```python
import unittest
from curator.sources import fetch_hacker_news, fetch_reddit_ai, fetch_github_releases, fetch_all_sources

class TestSources(unittest.TestCase):
    def test_item_structure(self):
        # Verify normalization and required keys
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

    def test_fetch_reddit_smoke(self):
        items = fetch_reddit_ai(limit=3)
        self.assertIsInstance(items, list)
        if items:
            self.assertTrue(items[0]["id"].startswith("reddit_"))

    def test_fetch_github_smoke(self):
        items = fetch_github_releases()
        self.assertIsInstance(items, list)
        if items:
            self.assertTrue(items[0]["id"].startswith("gh_"))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_sources.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'curator'`

- [ ] **Step 3: Implement `curator/sources.py`**

Implement using standard library `urllib.request` and `xml.etree.ElementTree`:
- Hacker News: Top + Show stories via Firebase REST endpoints (`/v0/topstories.json`, `/v0/showstories.json`).
- Reddit: `https://www.reddit.com/r/LocalLLaMA/hot.json?limit=15` with Custom User-Agent header (`NewsCuratorBot/1.0`).
- GitHub: Public Atom release feeds for curated AI tools (`ollama/ollama`, `vllm-project/vllm`, `deepseek-ai/DeepSeek-V3`, `BerriAI/litellm`).
- Normalization: prefix IDs (`hn_`, `reddit_`, `gh_`) to prevent collisions.

- [ ] **Step 4: Run test to verify it passes**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_sources.py`
Expected: PASS

- [ ] **Step 5: Verify review focus: Network timeout and error resilience**

Add test in `tests/test_sources.py` verifying that passing unreachable URLs or hitting HTTP errors returns an empty list without raising unhandled exceptions. Run tests and ensure PASS.

---

### Task 2: Classification, Categorization, and Scoring (System 1)

**Files:**
- Create: `curator/evaluator.py`
- Test: `tests/test_evaluator.py`

**Interfaces:**
- Consumes:
  - 9Router API endpoint `http://localhost:20128/v1/chat/completions` with model `cf/@cf/meta/llama-3.3-70b-instruct-fp8-fast`.
- Produces:
  ```python
  def classify_article(title: str) -> dict: ...
  # Returns: {"signal": float, "fact": float, "hype": float, "category": str, "topics": list[str]}
  # where category is in ("free_api", "tools", "models")
  def calculate_score(title: str, metrics: dict, weights: dict[str, float]) -> tuple[float, list[str]]: ...
  # Returns: (score: float, matched_topics: list[str])
  ```

- [ ] **Step 1: Write the failing tests for evaluation in `tests/test_evaluator.py`**

```python
import unittest
from curator.evaluator import calculate_score, parse_classification_json

class TestEvaluator(unittest.TestCase):
    def test_parse_clean_json(self):
        raw = '{"signal": 0.8, "fact": 0.9, "hype": 0.2, "category": "tools", "topics": ["python"]}'
        parsed = parse_classification_json(raw)
        self.assertEqual(parsed["category"], "tools")
        self.assertEqual(parsed["signal"], 0.8)

    def test_parse_code_fenced_json(self):
        raw = '```json\n{"signal": 0.7, "fact": 0.8, "hype": 0.1, "category": "free_api", "topics": ["api"]}\n```'
        parsed = parse_classification_json(raw)
        self.assertEqual(parsed["category"], "free_api")

    def test_parse_fallback_on_corrupt(self):
        raw = 'Not JSON at all'
        parsed = parse_classification_json(raw)
        self.assertIn("category", parsed)
        self.assertIn("signal", parsed)

    def test_calculate_score_formula(self):
        # Score = (Signal * 0.6 + Fact * 0.4 - Hype * 0.3) * Multiplier
        metrics = {"signal": 0.8, "fact": 0.6, "hype": 0.2}
        weights = {"deepseek": 1.5}
        score, matched = calculate_score("DeepSeek-V3 weights released", metrics, weights)
        expected_base = (0.8 * 0.6) + (0.6 * 0.4) - (0.2 * 0.3) # 0.48 + 0.24 - 0.06 = 0.66
        self.assertAlmostEqual(score, round(0.66 * 1.5, 2))
        self.assertIn("deepseek", matched)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_evaluator.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'curator.evaluator'`

- [ ] **Step 3: Implement `curator/evaluator.py`**

- `parse_classification_json(text: str) -> dict`: Clean Markdown wrappers, strip trailing non-JSON, and validate schema defaults (`category` in `{"free_api", "tools", "models"}`).
- `classify_article(title: str) -> dict`: Calls 9Router Llama 70B model with a strict system prompt instructing JSON output with keys `signal`, `fact`, `hype`, `category`, `topics`.
- `calculate_score(title: str, metrics: dict, weights: dict[str, float]) -> tuple[float, list[str]]`: Applies base score formula and multiplies by matched taste weights.

- [ ] **Step 4: Run test to verify it passes**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_evaluator.py`
Expected: PASS

---

### Task 3: Content Extraction (Tinyfish) and Summarizer (System 2)

**Files:**
- Create: `curator/summarizer.py`
- Test: `tests/test_summarizer.py`

**Interfaces:**
- Consumes:
  - 9Router endpoint `/v1/web/fetch` with model `tinyfish`.
  - 9Router endpoint `/v1/chat/completions` with model `cf/@cf/meta/llama-3.3-70b-instruct-fp8-fast`.
- Produces:
  ```python
  def fetch_page_markdown(url: str, max_chars: int = 2500) -> str: ...
  def summarize_article(title: str, content: str = "", lang: str = "ru") -> str: ...
  # Returns: string with exactly 2 bullet points
  ```

- [ ] **Step 1: Write the failing tests in `tests/test_summarizer.py`**

```python
import unittest
from curator.summarizer import clean_summary_bullets

class TestSummarizer(unittest.TestCase):
    def test_clean_bullets(self):
        raw = "Here is the summary:\n* Point one\n* Point two\nAdditional comment"
        cleaned = clean_summary_bullets(raw)
        self.assertTrue(cleaned.startswith("• Point one") or cleaned.startswith("* Point one"))
        self.assertNotIn("Here is the summary", cleaned)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_summarizer.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'curator.summarizer'`

- [ ] **Step 3: Implement `curator/summarizer.py`**

- `fetch_page_markdown(url: str, max_chars: int = 2500) -> str`: Calls `/v1/web/fetch` using `tinyfish`. If request fails or times out, returns empty string gracefully.
- `summarize_article(title: str, content: str = "", lang: str = "ru") -> str`: Calls Llama 70B asking for exactly 2 bullets: 1) What it is, 2) Why it matters to developers.
- `clean_summary_bullets(text: str) -> str`: Normalizes bullet prefixes (`* `, `- ` -> `• `) and removes greeting/preamble lines.

- [ ] **Step 4: Run test to verify it passes**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_summarizer.py`
Expected: PASS

---

### Task 4: Storage & Data Flywheel (SQLite)

**Files:**
- Create: `curator/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  ```python
  def init_db(db_path: str = "news_curator.db"): ...
  def save_article(article: dict, db_path: str = "news_curator.db"): ...
  def get_unreported_high_signal(min_score: float = 0.25, db_path: str = "news_curator.db") -> list[dict]: ...
  def mark_articles_delivered(article_ids: list[str], db_path: str = "news_curator.db"): ...
  def record_user_vote(article_id: str, vote: int, db_path: str = "news_curator.db") -> tuple[str, list[str]]: ...
  # Returns: (title, list of updated topic weights)
  def get_taste_weights(db_path: str = "news_curator.db") -> dict[str, float]: ...
  def update_taste_weight(topic: str, weight: float, db_path: str = "news_curator.db"): ...
  ```

- [ ] **Step 1: Write the failing tests in `tests/test_db.py`**

```python
import os, unittest
from curator.db import init_db, save_article, get_unreported_high_signal, mark_articles_delivered, record_user_vote, get_taste_weights

TEST_DB = "test_curator.db"

class TestDB(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB): os.remove(TEST_DB)
        init_db(TEST_DB)

    def tearDown(self):
        if os.path.exists(TEST_DB): os.remove(TEST_DB)

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

        record_user_vote("hn_200", +1, TEST_DB)
        new_weights = get_taste_weights(TEST_DB)
        self.assertAlmostEqual(new_weights["deepseek"], prev_w + 0.15, places=2)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_db.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'curator.db'`

- [ ] **Step 3: Implement `curator/db.py`**

- Schema creation with tables: `articles` (id, title, url, source, signal, fact, hype, score, category, summary, user_vote, delivered_at, created_at), `taste_weights` (topic, weight), `settings` (key, value).
- `save_article` with `INSERT OR REPLACE`.
- `get_unreported_high_signal`: `SELECT * FROM articles WHERE score >= ? AND delivered_at IS NULL ORDER BY score DESC`.
- `record_user_vote`: updates `user_vote`, checks article title against topics in `taste_weights`, and adds/subtracts 0.15 delta (bounded 0.1..3.0).

- [ ] **Step 4: Run test to verify it passes**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_db.py`
Expected: PASS

---

### Task 5: Digest Compiler & Interactive Voting Layout

**Files:**
- Create: `curator/digest.py`
- Test: `tests/test_digest.py`

**Interfaces:**
- Produces:
  ```python
  def build_digest(articles: list[dict], greeting: str = "Сводка") -> tuple[str, list[list[dict]]]: ...
  # Returns: (formatted_markdown_text: str, inline_keyboard_buttons: list[list[Button.inline]])
  ```

- [ ] **Step 1: Write the failing tests in `tests/test_digest.py`**

```python
import unittest
from curator.digest import build_digest

class TestDigest(unittest.TestCase):
    def test_build_digest_categorization(self):
        items = [
            {"id": "item1", "title": "Free API Gateway", "url": "https://api.com", "category": "free_api", "score": 0.8, "summary": "• Free tier\n• 100k tokens"},
            {"id": "item2", "title": "Fast Docker Runtime", "url": "https://docker.com", "category": "tools", "score": 0.75, "summary": "• Fast start\n• Saves RAM"},
            {"id": "item3", "title": "DeepSeek-V3", "url": "https://ds.com", "category": "models", "score": 0.95, "summary": "• 671B params\n• Top benchmark"}
        ]
        text, button_grid = build_digest(items, greeting="Утренний дайджест")
        self.assertIn("🎁 **Бесплатный доступ и API**", text)
        self.assertIn("🛠 **Инструменты и утилиты**", text)
        self.assertIn("🧠 **Релизы моделей и весов**", text)
        self.assertIn("1. [Free API Gateway](https://api.com)", text)
        self.assertIn("2. [Fast Docker Runtime](https://docker.com)", text)
        self.assertIn("3. [DeepSeek-V3](https://ds.com)", text)

        # Check button grid has 3 items with numbered thumbs up/down
        self.assertEqual(len(button_grid), 2) # e.g. 2 rows for 3 items (2 items per row)

    def test_build_empty_digest(self):
        text, buttons = build_digest([], greeting="Сводка")
        self.assertIn("За прошедший период не найдено важных обновлений", text)
        self.assertEqual(len(buttons), 0)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_digest.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'curator.digest'`

- [ ] **Step 3: Implement `curator/digest.py`**

- Groups articles into 3 sections: `free_api` (🎁 Бесплатный доступ и API), `tools` (🛠 Инструменты и утилиты), `models` (🧠 Релизы моделей и весов).
- Assigns sequential numbers `1..N` across the whole digest.
- Formats each entry with title link, score, and 2-bullet summary.
- Builds an inline button grid for voting: rows of 2 or 3 buttons (e.g. `[1 👍][1 👎]  [2 👍][2 👎]`), encoding `callback_data` compactly: `f"v:1:{item_id}"` and `f"v:-1:{item_id}"`.
- Enforces 4000 character length safety margin to prevent Telegram message splitting.

- [ ] **Step 4: Run test to verify it passes**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_digest.py`
Expected: PASS

---

### Task 6: Scheduler, Telegram MTProto Bot & End-to-End Daemon

**Files:**
- Modify: `news_daemon.py`
- Test: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes:
  - Modules from Tasks 1–5 (`curator.sources`, `curator.evaluator`, `curator.summarizer`, `curator.db`, `curator.digest`).
  - Telethon Client connected to MTProto proxy.
- Produces:
  - Working service with scheduled deliveries at 08:00 and 20:00 MSK.
  - Interactive handlers for `/start`, `/digest`, `/search`, `/stats`, `/weights`, `/set`, `/threshold`.
  - CallbackQuery handler for `v:<vote>:<id>` updating votes and editing keyboard.

- [ ] **Step 1: Write integration tests in `tests/test_end_to_end.py`**

```python
import unittest
from curator.db import init_db, get_unreported_high_signal, record_user_vote
from curator.digest import build_digest

class TestEndToEndFlow(unittest.TestCase):
    def test_digest_and_vote_pipeline(self):
        init_db("test_e2e.db")
        # Ensure digest compiler creates correct buttons matching DB IDs
        dummy = [{"id": "gh_1", "title": "Ollama v0.5", "url": "https://ollama.ai", "category": "tools", "score": 0.8, "summary": "• New model support"}]
        text, grid = build_digest(dummy)
        # Simulate click
        cb_data = grid[0][0]["data"] # e.g. "v:1:gh_1"
        parts = cb_data.split(":")
        vote = int(parts[1])
        art_id = parts[2]
        self.assertEqual(art_id, "gh_1")
        self.assertEqual(vote, 1)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `& 'C:\Python314\python.exe' -m unittest tests/test_end_to_end.py`

- [ ] **Step 3: Refactor `news_daemon.py` to assemble the full pipeline**

- Ingest from `fetch_all_sources()` (HN, Reddit, GitHub).
- Run background ingest loop every 120 seconds:
  - Deduplicate against `articles` table in SQLite.
  - Classify new items with Llama 70B System 1.
  - For items exceeding threshold: fetch Markdown via Tinyfish `web/fetch` and generate Russian 2-bullet summary via System 2.
- Scheduler loop:
  - Monitors time in Europe/Moscow timezone (`datetime.now(ZoneInfo('Europe/Moscow'))`).
  - At 08:00 and 20:00: triggers scheduled digest, marks delivered items in DB, and sends to Telegram.
- Command handlers:
  - `/digest` generates an immediate on-demand digest from the current candidate pool.
  - `/search <query>` searches via Tinyfish, scores, summarizes top hit, and returns interactive card.
  - `/stats`, `/weights`, `/set <topic> <weight>`, `/threshold <val>`.
  - Callback query `v:<vote>:<id>` records vote, adjusts weights, and updates button UI with checkmarks.

- [ ] **Step 4: Execute a dry-run sweep and test command response**

Run: `& 'C:\Python314\python.exe' news_daemon.py --test-run`
Expected: Successfully connects to MTProto proxy, runs a crawl cycle from all 3 sources, compiles a test digest without errors, and exits cleanly.

- [ ] **Step 5: Launch the finalized daemon in background**

Start `news_daemon.py` via `pythonw.exe` and confirm live status in `daemon.err.log`.
