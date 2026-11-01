# Design: Proactive Multi-Source News Curator & Scheduled Digest

## 1. Intent & Purpose
The user does not follow daily news feeds but wants high-signal, concise, and actionable technical updates without information overload or message spam. The bot acts as an autonomous engineer-curator that continuously collects, verifies, scores, and compiles technical news into structured digests delivered twice a day (and on-demand).

## 2. Goals, Non-Goals & Anti-Goals
### Goals
- **Aggregated Multi-Source Intelligence:** Aggregate and deduplicate technical news from multiple high-signal sources:
  - Hacker News (Firebase API: top & show stories).
  - Reddit (JSON feeds for r/LocalLLaMA, r/MachineLearning).
  - GitHub Releases / Trending (AI tools, runtimes, agents).
  - Web Search via 9Router Tinyfish (`/v1/search`) for free API drops and emerging tools.
- **Strict Relevance Filter:** High focus on:
  - Open-source AI models & weights (DeepSeek, Llama, Qwen, Mistral).
  - Practical AI/developer tools, local inference runtimes, agent frameworks.
  - Free API access methods, proxies, token routes, and gateway hacks.
- **Zero-Spam Delivery Mode:** No real-time message spamming. Instead:
  - Scheduled Morning Digest at **08:00 MSK**.
  - Scheduled Evening Digest at **20:00 MSK**.
  - On-Demand Digest at any time via `/digest` command or inline button.
- **Structured Digest Format:** Single clean Telegram message in Russian (or user-chosen language via `/lang`) organized by sections:
  - 🎁 **Бесплатный доступ и API** (free APIs, routes, free tiers).
  - 🛠 **Инструменты и утилиты** (developer tools, libraries, runtimes).
  - 🧠 **Релизы моделей и весов** (new architectures, weights, benchmarks).
  - Each item: title as link, score badge, and exactly 2 concise sentences explaining what it is and its practical engineering impact.
- **Deep Extraction via Web Fetch:** Top-ranked candidate items have their actual web page fetched in Markdown format via Tinyfish (`/v1/web/fetch`) before summarization, ensuring fact-based summaries rather than headline hallucinations.
- **Interactive Data Flywheel:** Retain thumbs up / down feedback (`👍` / `👎`) to continuously adjust topic weights in SQLite.

### Non-Goals
- Real-time instant alerts for every news item (anti-goal: avoid notification fatigue).
- Full conversational AI chat outside of curator commands and web search.

### Anti-Goals (Strict Negative Filters)
- Zero politics, geopolitical commentary, or corporate drama.
- Zero marketing puff pieces (e.g. "Company raises $X million to build undefined AI").
- Zero generic opinions and speculative thinkpieces lacking working code, models, or APIs.

## 3. Architecture & Technical Constraints
- **Platform & Runtime:** Python 3.14 on Windows host, single-daemon background process.
- **Telegram Connection:** Telethon via MTProto proxy acting as bot communicating with chat.
- **LLM & Search Gateway (9Router on `http://localhost:20128`):**
  - **Gate & Filter (System 1):** `cf/@cf/meta/llama-3.3-70b-instruct-fp8-fast` returning strict JSON `{signal, fact, hype, category, topics}` where category is one of `free_api`, `tools`, `models`.
  - **Content Fetcher:** `/v1/web/fetch` using `tinyfish` for article markdown.
  - **Summarizer (System 2):** `cf/@cf/meta/llama-3.3-70b-instruct-fp8-fast` producing 2-bullet Russian summaries based on fetched page markdown.
  - **On-Demand Search:** `/v1/search` using `tinyfish`.
- **Source Ingestion Strategy (Builder's Call):**
  - **Hacker News:** Firebase API (topstories + showstories).
  - **Reddit:** Public JSON API (`/r/LocalLLaMA/hot.json`, `/r/MachineLearning/hot.json`) with standard User-Agent.
  - **GitHub:** Public Atom/RSS feeds for curated top AI repos (e.g. Ollama, vLLM, DeepSeek, LiteLLM) and trending mirrors, requiring zero API keys and avoiding rate limits.
  - **Web Search:** Dedicated on-demand `/search` command, plus background discovery rotation for emerging free API proxies.
- **Article Lifecycle & Deduplication (Builder's Call):**
  - Scheduled digests (08:00 and 20:00 MSK) take the top-scored items from the preceding 12-hour window and mark them with `delivered_at`.
  - On-demand `/digest` delivers a current snapshot without draining the scheduled morning/evening digest.
- **Telegram Connection:**
  - Active Telethon MTProto session over proxy using configured environment credentials (`API_ID`, `API_HASH`, bot token).

### Interactive Voting UX (All Items Rated)
- Every item in the consolidated digest is numbered (`1.`, `2.`, ... `N`).
- Below the digest message, an inline keyboard provides quick-vote buttons for each item in a compact 2-column or 3-column grid (e.g. `[#1 👍] [#1 👎]`, `[#2 👍] [#2 👎]`, etc.).
- When a button is clicked:
  - The vote is persisted in SQLite (`user_vote` = +1 or -1).
  - The topic weights in `taste_weights` associated with that article are dynamically adjusted ($\pm 0.15$).
  - The button label updates to show current state (e.g. `[#1 ✅]` / `[#1 👎]`) and an inline toast confirms the weight shift.

## 4. User Interaction & Commands
- `/start` or `/help` — Overview, current schedule, taste weights, and quick action buttons.
- `/digest` — Instantly compiles and sends the current pending digest of top news.
- `/search <query>` — Performs live web search via Tinyfish, scores results, and summarizes top hit.
- `/stats` — Processing metrics (total scanned, filtered out, passed, user votes).
- `/weights` & `/set <topic> <weight>` — View and update topic weights.
- `/lang <ru|en>` — Select digest language (Russian default).

## 5. Left to the Builder
- Specific HTTP client timeouts and retry backoffs for Reddit/GitHub feeds.
- Maximum number of items per digest category (recommended: 3-5 top items per section to keep the message within Telegram 4096-char limit).
- Exact text truncation logic for extra-large web fetches.
