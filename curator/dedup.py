"""
curator/dedup.py - Event deduplication: collapse the same news arriving from
multiple sources (TG, Reddit, HN, GitHub, HF) into one cluster.
"""
import re, json, logging

log = logging.getLogger("curator.dedup")

# Words carrying no discriminating signal
STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "from", "into", "about", "this", "that",
    "new", "now", "release", "released", "releases", "update", "updated", "version", "v",
    "out", "is", "are", "to", "of", "in", "on", "by", "at", "as", "its", "it", "we",
    "show", "hn", "news", "announcing", "announce", "introducing", "available",
    "и", "в", "на", "с", "для", "по", "это", "как", "что", "новый", "новая", "новое", "новые",
    "релиз", "вышел", "вышла", "вышли", "обновление", "версия", "теперь", "уже", "можно",
    "представил", "представила", "представили", "выпустил", "выпустила", "выпустили",
    "анонсировал", "анонсировала", "анонсировали", "показал", "показала", "показали",
    "рассказал", "рассказала", "рассказали", "объявил", "объявила", "объявили",
    "pro", "max", "mini", "plus", "ultra", "lite"
}

SOURCE_LABELS = {
    "github": "GitHub",
    "reddit": "Reddit",
    "hn": "HN",
    "huggingface": "HF",
    "telegram": "TG",
    "tg": "TG",
    "rozetked": "Rozetked",
    "securitylab": "SecurityLab",
    "3dnews": "3DNews",
    "habr": "Habr",
}

PR_RE = re.compile(r"#(\d{3,6})")

# Build/version identifiers carry no identity signal: b11792, v0.6.3, 2024.1
VERSION_RE = re.compile(r"^[a-z]?\d+(?:[.\-]\d+)*$", re.IGNORECASE)


RU_ENDINGS = re.compile(r"(?:ами|ями|ией|иям|ом|ем|ой|ей|ью|а|я|у|ю|ы|и|е|о)$")


def normalize_token(tok: str) -> str:
    """Normalize token: strip common Russian inflection endings while preserving English words."""
    if re.search(r"[а-я]", tok) and len(tok) >= 5:
        return RU_ENDINGS.sub("", tok)
    return tok


def significant_tokens(title: str) -> set[str]:
    """Lowercase alphanumeric tokens minus stopwords and build/version numbers."""
    t = (title or "").lower()
    # split on every non-word char, so "open-sources" == "open sources"
    raw = re.split(r"[^\w]+", t, flags=re.UNICODE)
    out = set()
    for tok in raw:
        tok = tok.strip("_")
        if len(tok) < 3 or tok in STOPWORDS:
            continue
        if VERSION_RE.match(tok):
            continue
        out.add(normalize_token(tok))
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: set[str], b: set[str]) -> float:
    """Share of the smaller set covered by the other - robust to extra words."""
    if not a or not b:
        return 0.0
    shared = a & b
    if len(shared) < 2:
        return 0.0
    return len(shared) / min(len(a), len(b))


def similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    j = jaccard(a, b)
    if j >= 0.50:
        return j
    shared = a & b
    if len(shared) >= 3 and j >= 0.30:
        c = len(shared) / min(len(a), len(b))
        if c >= 0.70:
            return c
    return j


def extract_pr_number(title: str) -> str:
    m = PR_RE.search(title or "")
    return m.group(1) if m else ""


def extract_repo(url: str) -> str:
    m = re.search(r"github\.com/([^/]+/[^/]+)", url or "")
    return m.group(1).lower() if m else ""


def source_label(source: str) -> str:
    return SOURCE_LABELS.get((source or "").lower(), (source or "web").capitalize())


def find_duplicate(heads: list[dict], title: str, url: str, threshold: float = 0.55) -> dict | None:
    """Return the cluster head matching this item, or None.

    `heads` are recent rows where cluster_id == id (dedupe candidates).
    Match order: identical URL -> same PR number in same repo -> token Jaccard.
    """
    tok_new = significant_tokens(title)
    pr_new = extract_pr_number(title)
    repo_new = extract_repo(url)

    for head in heads:
        if url and head.get("url") == url:
            return head

        pr_head = extract_pr_number(head.get("title", ""))
        if pr_new and pr_new == pr_head:
            repo_head = extract_repo(head.get("url", ""))
            if not repo_new or not repo_head or repo_new == repo_head:
                return head

        if similarity(tok_new, significant_tokens(head.get("title", ""))) >= threshold:
            return head

    return None


def build_source_entry(title: str, url: str, source: str) -> dict:
    return {"source": source_label(source), "title": (title or "")[:120], "url": url or ""}


def parse_sources(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def merge_sources(existing_raw: str, entry: dict) -> str:
    """Append a source entry, skipping the same label+url twice."""
    sources = parse_sources(existing_raw)
    key = (entry.get("source"), entry.get("url"))
    if any((s.get("source"), s.get("url")) == key for s in sources):
        return json.dumps(sources, ensure_ascii=False)
    sources.append(entry)
    return json.dumps(sources, ensure_ascii=False)


def format_discussion_line(sources_raw: str) -> str:
    """Render 'Обсуждают: [Reddit](..) · [HN](..)' or '' when there is nothing extra."""
    sources = parse_sources(sources_raw)
    if not sources:
        return ""
    parts = []
    seen = set()
    for s in sources:
        label = s.get("source") or "web"
        if label in seen:
            continue
        seen.add(label)
        url = s.get("url") or ""
        parts.append(f"[{label}]({url})" if url else label)
    if not parts:
        return ""
    return "  🔗 Обсуждают: " + " · ".join(parts)
