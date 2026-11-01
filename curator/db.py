"""
curator/db.py - SQLite storage with WAL mode, candidate pooling, and taste weight feedback.
"""
import sqlite3, logging
from contextlib import contextmanager

log = logging.getLogger("curator.db")

DEFAULT_WEIGHTS = {
    "docker": 1.3,
    "linux": 1.2,
    "python": 1.2,
    "deepseek": 1.3,
    "sqlite": 1.2,
    "crypto": 0.3,
    "ai": 1.1,
    "agent": 1.2,
    "api": 1.2
}

@contextmanager
def db_session(db_path: str = "news_curator.db"):
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db(db_path: str = "news_curator.db"):
    with db_session(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                title TEXT,
                url TEXT,
                source TEXT,
                signal REAL,
                fact REAL,
                hype REAL,
                score REAL,
                category TEXT DEFAULT 'tools',
                summary TEXT,
                user_vote INTEGER DEFAULT 0,
                delivered_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migration check
        cols = [c["name"] for c in conn.execute("PRAGMA table_info(articles)").fetchall()]
        if "category" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN category TEXT DEFAULT 'tools'")
        if "delivered_at" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN delivered_at TIMESTAMP")
        if "source" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN source TEXT")
        if "user_vote" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN user_vote INTEGER DEFAULT 0")
        if "cluster_id" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN cluster_id TEXT")
        if "sources" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN sources TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS taste_weights (
                topic TEXT PRIMARY KEY,
                weight REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        for topic, w in DEFAULT_WEIGHTS.items():
            conn.execute("INSERT OR IGNORE INTO taste_weights (topic, weight) VALUES (?, ?)", (topic, w))
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('threshold', '0.25')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('lang', 'ru')")

def save_article(art: dict, db_path: str = "news_curator.db"):
    with db_session(db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO articles (
                id, title, url, source, signal, fact, hype, score, category, summary, user_vote, delivered_at,
                cluster_id, sources
            ) VALUES (
                :id, :title, :url, :source, :signal, :fact, :hype, :score, :category, :summary,
                COALESCE((SELECT user_vote FROM articles WHERE id = :id), 0),
                (SELECT delivered_at FROM articles WHERE id = :id),
                :cluster_id, :sources
            )
        """, {
            "id": art["id"],
            "title": art["title"],
            "url": art["url"],
            "source": art.get("source", "hn"),
            "signal": float(art.get("signal", 0.0)),
            "fact": float(art.get("fact", 0.0)),
            "hype": float(art.get("hype", 0.0)),
            "score": float(art.get("score", 0.0)),
            "category": art.get("category", "tools"),
            "summary": art.get("summary"),
            "cluster_id": art.get("cluster_id") or art["id"],
            "sources": art.get("sources") or "[]"
        })

def get_cluster_heads(hours: int = 72, db_path: str = "news_curator.db") -> list[dict]:
    """Recent cluster heads used as dedupe candidates."""
    with db_session(db_path) as conn:
        rows = conn.execute("""
            SELECT id, title, url, source, cluster_id, sources
            FROM articles
            WHERE (cluster_id IS NULL OR cluster_id = id)
              AND created_at >= datetime('now', ?)
            ORDER BY created_at DESC
            LIMIT 400
        """, (f"-{int(hours)} hours",)).fetchall()
        return [dict(r) for r in rows]

def update_cluster_sources(cluster_id: str, sources_json: str, db_path: str = "news_curator.db"):
    with db_session(db_path) as conn:
        conn.execute("UPDATE articles SET sources = ? WHERE id = ?", (sources_json, cluster_id))

def get_unreported_high_signal(min_score: float = 0.25, limit: int = 15, db_path: str = "news_curator.db") -> list[dict]:
    with db_session(db_path) as conn:
        rows = conn.execute("""
            SELECT id, title, url, source, signal, fact, hype, score, category, summary, user_vote,
                   cluster_id, sources
            FROM articles
            WHERE score >= ? AND summary IS NOT NULL AND delivered_at IS NULL
              AND (cluster_id IS NULL OR cluster_id = id)
            ORDER BY score DESC
            LIMIT ?
        """, (min_score, limit)).fetchall()
        return [dict(r) for r in rows]

def get_latest_high_signal(min_score: float = 0.25, limit: int = 15, db_path: str = "news_curator.db") -> list[dict]:
    with db_session(db_path) as conn:
        rows = conn.execute("""
            SELECT id, title, url, source, signal, fact, hype, score, category, summary, user_vote,
                   cluster_id, sources
            FROM articles
            WHERE score >= ? AND summary IS NOT NULL
              AND (cluster_id IS NULL OR cluster_id = id)
            ORDER BY score DESC, created_at DESC
            LIMIT ?
        """, (min_score, limit)).fetchall()
        return [dict(r) for r in rows]

def mark_cluster_delivered(cluster_id: str, db_path: str = "news_curator.db"):
    """Mark a whole event (head + its duplicates) as delivered."""
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE articles SET delivered_at = CURRENT_TIMESTAMP WHERE id = ? OR cluster_id = ?",
            (cluster_id, cluster_id)
        )

def mark_articles_delivered(article_ids: list[str], db_path: str = "news_curator.db"):
    if not article_ids:
        return
    with db_session(db_path) as conn:
        placeholders = ",".join("?" for _ in article_ids)
        conn.execute(f"UPDATE articles SET delivered_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})", article_ids)

def get_taste_weights(db_path: str = "news_curator.db") -> dict[str, float]:
    with db_session(db_path) as conn:
        return dict(conn.execute("SELECT topic, weight FROM taste_weights").fetchall())

def update_taste_weight(topic: str, weight: float, db_path: str = "news_curator.db"):
    with db_session(db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO taste_weights (topic, weight) VALUES (?, ?)", (topic.lower(), round(weight, 2)))

def record_user_vote(article_id: str, vote: int, db_path: str = "news_curator.db") -> tuple[str | None, list[str]]:
    with db_session(db_path) as conn:
        row = conn.execute("SELECT title, user_vote FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            return None, []
        title = row["title"]
        conn.execute("UPDATE articles SET user_vote = ? WHERE id = ?", (vote, article_id))

    delta = 0.15 if vote > 0 else -0.15
    adjusted = []
    current_weights = get_taste_weights(db_path)
    t_lower = title.lower()
    for topic, current_w in current_weights.items():
        if topic in t_lower:
            new_w = round(max(0.1, min(3.0, current_w + delta)), 2)
            update_taste_weight(topic, new_w, db_path)
            adjusted.append(f"{topic} -> {new_w:.2f}")
    return title, adjusted

def get_setting(key: str, default: str = "", db_path: str = "news_curator.db") -> str:
    with db_session(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

def set_setting(key: str, value: str, db_path: str = "news_curator.db"):
    with db_session(db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
