# News Curator & Digest Bot

Autonomous AI-powered technical news curator and scheduled digest bot for Telegram.

## Features
- **Multi-Source Ingestion**: Monitors GitHub Releases, Hacker News, Reddit, and curated Telegram channels.
- **AI Filtering & Scoring (System 1)**: Filters noise and classifies articles into categories (`models`, `tools`, `free_api`, `local_ai`, `agents`, etc.).
- **Content Enrichment**: Fetches article markdown via web fetch and generates summaries.
- **Multi-Agent Editorial Pipeline (System 2)**: Drafts, fact-checks, refines, and formats posts for Telegram.
- **Interactive Feedback**: In-line Telegram voting adjusts recommendation weights in SQLite.
- **Scheduled Digests**: Daily morning and evening digests + on-demand `/digest` command.

## Quick Start
1. Copy `.env.example` to `.env` and fill in credentials:
   ```bash
   cp .env.example .env
   ```
2. Install dependencies:
   ```bash
   pip install telethon
   ```
3. Run the daemon:
   ```bash
   python news_daemon.py
   ```
