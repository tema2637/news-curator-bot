"""
curator/sources.py - Ingestion crawlers for Hugging Face, GitHub Releases, Reddit AI, and Hacker News.
Strict freshness filter: only items published/released within the last 72-96 hours.
"""
import asyncio, json, logging, time, datetime, re, urllib.request, urllib.error, email.utils, hashlib
import xml.etree.ElementTree as ET

log = logging.getLogger("curator.sources")

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsCuratorBot/2.0"

# Curated high-impact AI developer tools and model repositories
CURATED_GITHUB_REPOS = [
    ("comfyanonymous/ComfyUI", "ComfyUI"),
    ("ggerganov/llama.cpp", "llama.cpp"),
    ("vllm-project/vllm", "vLLM"),
    ("ollama/ollama", "Ollama"),
    ("sgl-project/sglang", "SGLang"),
    ("huggingface/transformers", "Transformers"),
    ("huggingface/diffusers", "Diffusers"),
    ("BerriAI/litellm", "LiteLLM"),
    ("deepseek-ai/DeepSeek-V3", "DeepSeek-V3"),
    ("QwenLM/Qwen2.5", "Qwen2.5")
]

MAX_AGE_SECONDS = 4 * 86400  # Max 4 days old

def safe_fetch_json(url: str, headers: dict = None, timeout: int = 6):
    h = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        log.warning("safe_fetch_json error for %s: %s", url, e)
        return None

def fetch_huggingface_trending(limit: int = 15) -> list[dict]:
    """Fetches trending AI models from Hugging Face that were created or updated recently."""
    items = []
    url = f"https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit={limit}&full=true"
    data = safe_fetch_json(url, timeout=8)
    if not data or not isinstance(data, list):
        return items

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    for m in data:
        mid = m.get("id")
        if not mid:
            continue

        created_str = m.get("createdAt") or m.get("lastModified")
        if created_str:
            try:
                dt = datetime.datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                age = (now_utc - dt).total_seconds()
                if age > MAX_AGE_SECONDS:
                    continue
            except Exception:
                pass

        ptag = m.get("pipeline_tag") or "AI Model"
        likes = m.get("likes", 0)
        desc = m.get("description") or ""
        tags = ", ".join(str(t) for t in m.get("tags", [])[:8])
        items.append({
            "id": "hf_" + mid.replace("/", "_"),
            "title": f"[HuggingFace] {mid} — {ptag} (👍 {likes})",
            "url": f"https://huggingface.co/{mid}",
            "source": "huggingface",
            "content": f"Pipeline: {ptag}\nTags: {tags}\n{desc}"
        })
    return items

def fetch_github_releases() -> list[dict]:
    """Fetches GitHub releases only if updated within MAX_AGE_SECONDS."""
    items = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    for repo, display_name in CURATED_GITHUB_REPOS:
        atom_url = f"https://github.com/{repo}/releases.atom"
        req = urllib.request.Request(atom_url, headers={"User-Agent": DEFAULT_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                xml_data = resp.read().decode("utf-8", errors="replace")
                root = ET.fromstring(xml_data)
                entries = root.findall("atom:entry", ns)
                for entry in entries[:2]:
                    updated_elem = entry.find("atom:updated", ns)
                    if updated_elem is not None and updated_elem.text:
                        try:
                            dt = datetime.datetime.fromisoformat(updated_elem.text.replace("Z", "+00:00"))
                            age = (now_utc - dt).total_seconds()
                            if age > MAX_AGE_SECONDS:
                                continue  # Skip stale releases!
                        except Exception:
                            pass

                    title_elem = entry.find("atom:title", ns)
                    link_elem = entry.find("atom:link", ns)
                    id_elem = entry.find("atom:id", ns)
                    title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    link = link_elem.attrib.get("href", "") if link_elem is not None else ""
                    entry_id = id_elem.text.strip() if id_elem is not None and id_elem.text else link
                    if title and link:
                        clean_id = entry_id.split("/")[-1]
                        content_elem = entry.find("atom:content", ns)
                        body_text = content_elem.text.strip() if content_elem is not None and content_elem.text else ""
                        clean_body = re.sub(r"<[^>]+>", " ", body_text)
                        items.append({
                            "id": f"gh_{repo.replace('/', '_')}_{clean_id}",
                            "title": f"[{display_name}] {title}",
                            "url": link,
                            "source": "github",
                            "content": clean_body[:1200]
                        })
        except Exception as e:
            log.warning("GitHub Atom fetch error for %s: %s", repo, e)
            continue
    return items

def fetch_reddit_ai(limit: int = 15) -> list[dict]:
    """Fetches Reddit AI announcements, filtering out questions and old megathreads."""
    items = []
    subs = ["LocalLLaMA", "MachineLearning"]
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    BAD_PATTERNS = re.compile(r"(\?|megathread|showcase|anyone else|help me|which one|worth it|budget upgrade|setup|troubleshoot)", re.I)

    for sub in subs:
        url = f"https://www.reddit.com/r/{sub}/hot.rss?limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                xml_data = resp.read().decode("utf-8", errors="replace")
                root = ET.fromstring(xml_data)
                entries = root.findall("atom:entry", ns)
                for entry in entries:
                    title_elem = entry.find("atom:title", ns)
                    link_elem = entry.find("atom:link", ns)
                    id_elem = entry.find("atom:id", ns)
                    updated_elem = entry.find("atom:updated", ns)

                    title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    link = link_elem.attrib.get("href", "") if link_elem is not None else ""
                    raw_id = id_elem.text.strip() if id_elem is not None and id_elem.text else link
                    pid = raw_id.split("/")[-1].replace("t3_", "")

                    # Check freshness
                    if updated_elem is not None and updated_elem.text:
                        try:
                            dt = datetime.datetime.fromisoformat(updated_elem.text.replace("Z", "+00:00"))
                            if (now_utc - dt).total_seconds() > 2 * 86400:
                                continue
                        except Exception:
                            pass

                    # Filter out user questions and megathreads
                    if BAD_PATTERNS.search(title):
                        continue

                    if title and link:
                        content_elem = entry.find("atom:content", ns)
                        body_text = content_elem.text.strip() if content_elem is not None and content_elem.text else ""
                        clean_body = re.sub(r"<[^>]+>", " ", body_text)
                        items.append({
                            "id": f"reddit_{pid}",
                            "title": title,
                            "url": link,
                            "source": "reddit",
                            "content": clean_body[:1200]
                        })
                    if len(items) >= limit:
                        break
        except Exception as e:
            log.warning("Reddit RSS fetch error for %s: %s", sub, e)
            continue
    return items

def fetch_hacker_news(limit: int = 20) -> list[dict]:
    """Fetches Hacker News AI/tool items with strict freshness and year check."""
    items = []
    top_ids = safe_fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=8) or []
    show_ids = safe_fetch_json("https://hacker-news.firebaseio.com/v0/showstories.json", timeout=8) or []

    combined_ids = []
    seen_ids = set()
    for sid in show_ids[:limit] + top_ids[:limit]:
        if sid not in seen_ids:
            seen_ids.add(sid)
            combined_ids.append(sid)
        if len(combined_ids) >= limit:
            break

    now_ts = time.time()
    # Reject titles with historical years like (2014), (2020), (2024)
    OLD_YEAR_PATTERN = re.compile(r"\((?:19\d\d|20[0-1]\d|202[0-5])\)")

    for sid in combined_ids:
        data = safe_fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=4)
        if not data or "title" not in data:
            continue

        title = data.get("title", "")
        item_time = data.get("time", 0)

        # Freshness: max 36 hours old
        if now_ts - item_time > 36 * 3600:
            continue

        # Skip old historical reposts
        if OLD_YEAR_PATTERN.search(title):
            continue

        items.append({
            "id": f"hn_{sid}",
            "title": title,
            "url": data.get("url", f"https://news.ycombinator.com/item?id={sid}"),
            "source": "hn"
        })
    return items

CURATED_TECH_RSS = [
    ("rozetked", "https://rozetked.me/rss.xml", 15),
    ("securitylab", "https://www.securitylab.ru/_services/export/rss/news/", 15),
    ("3dnews", "https://3dnews.ru/news/rss/", 15),
    ("habr", "https://habr.com/ru/rss/hubs/artificial_intelligence/articles/?fl=ru", 15),
    ("habr", "https://habr.com/ru/rss/news/", 15),
]

def fetch_tech_rss(limit_per_feed: int = 15) -> list[dict]:
    """Fetches news from curated Russian IT & Tech RSS portals (Rozetked, SecurityLab, 3DNews, Habr)."""
    items = []
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    for source_name, feed_url, feed_limit in CURATED_TECH_RSS:
        max_fetch = min(feed_limit, limit_per_feed)
        try:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                xml_data = resp.read().decode("utf-8", errors="replace")
                root = ET.fromstring(xml_data)
                feed_items = root.findall(".//item")
                count = 0
                for it in feed_items:
                    title = (it.findtext("title") or "").strip()
                    link = (it.findtext("link") or "").strip()
                    guid = (it.findtext("guid") or link).strip()
                    pub_date = (it.findtext("pubDate") or "").strip()
                    desc = (it.findtext("description") or "").strip()

                    if not title or not link:
                        continue

                    if pub_date:
                        try:
                            dt = email.utils.parsedate_to_datetime(pub_date)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=datetime.timezone.utc)
                            age = (now_utc - dt).total_seconds()
                            if age > MAX_AGE_SECONDS:
                                continue
                        except Exception:
                            pass

                    clean_desc = re.sub(r"<[^>]+>", " ", desc).strip()
                    clean_desc = re.sub(r"\s+", " ", clean_desc)

                    clean_guid = re.sub(r"[^a-zA-Z0-9_\-]", "", guid)
                    if len(clean_guid) > 30 or not clean_guid:
                        clean_guid = hashlib.md5((guid or link).encode("utf-8")).hexdigest()[:16]

                    items.append({
                        "id": f"{source_name}_{clean_guid}",
                        "title": title,
                        "url": link,
                        "source": source_name,
                        "content": clean_desc[:1200]
                    })
                    count += 1
                    if count >= max_fetch:
                        break
        except Exception as e:
            log.warning("RSS fetch error for %s (%s): %s", source_name, feed_url, e)
    return items

def fetch_all_sources(hn_limit: int = 20, reddit_limit: int = 15, hf_limit: int = 15, rss_limit: int = 15) -> list[dict]:
    combined = []
    seen_urls = set()

    # 1. Hugging Face Trending (Top priority for new models/weights)
    for item in fetch_huggingface_trending(limit=hf_limit):
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            combined.append(item)

    # 2. GitHub Releases (Top priority for local AI tools ComfyUI, llama.cpp, vLLM, Ollama)
    for item in fetch_github_releases():
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            combined.append(item)

    # 3. Hacker News (Recent tech announcements)
    for item in fetch_hacker_news(limit=hn_limit):
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            combined.append(item)

    # 4. Reddit AI (Community discoveries)
    for item in fetch_reddit_ai(limit=reddit_limit):
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            combined.append(item)

    # 5. Russian Tech & Dev Portals (Rozetked, SecurityLab, 3DNews, Habr)
    for item in fetch_tech_rss(limit_per_feed=rss_limit):
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            combined.append(item)

    return combined

CURATED_TG_CHANNELS = [
    "whackdoor",      # Бэкдор — вайб-кодинг, имба-сервисы, ИИ-утилиты, пет-проекты
    "forgetmeai",     # ForgetMe | Нейросети — обзоры моделей, инциденты, новые релизы
    "ai_for_devs",    # AI for Devs — бенчи, prompt caching, архитектуры, пайплайны
    "NoBlok",         # NoBlok | AI — бесплатные токены, промокоды, халява на LLM
    "neurorazvedka",  # НЕЙРОРАЗВЕДКА — генеративный ИИ, видеомодели, софт
    "seeallochnaya",  # Сиолошная — глубокая ML-аналитика, инсайты
    "neuralmeduza",   # Neural Meduza — оперативные AI-новости и софт
    "dlinnlp",        # DL in NLP — открытые архитектуры и исследования
    "gonzo_ML"        # Gonzo ML — разборы свежих ML-статей
]

AD_PATTERNS = re.compile(
    r'(#реклама\b|erid:\b|токен рекламы|подпишитесь на спонсора|розыгрыш\b|'
    r'СберИнвестици|Точка Банк|Альфа[- ]?Банк|Тинькофф|Т-Банк|курсы по wildberries|'
    r'крипта в россии.*всё)',
    re.I
)

async def fetch_telegram_channels(client, channels: list[str] = None, limit_per_channel: int = 4) -> list[dict]:
    """Crawl curated Telegram channels for fresh AI, tool, and dev posts via Telethon."""
    if not client:
        return []
    if channels is None:
        channels = CURATED_TG_CHANNELS

    from telethon.tl.types import InputMessageID, Message
    from telethon.tl.functions.channels import GetMessagesRequest
    from curator.db import get_setting, set_setting

    items = []
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    max_age_seconds = 3 * 86400  # 3 days

    for ch in channels:
        try:
            entity = await client.get_entity(ch)
            last_id_str = get_setting(f"tg_last_id:{ch}", "0")
            last_id = int(last_id_str) if last_id_str.isdigit() else 0

            msgs = []
            if last_id <= 0:
                # Bootstrap discovery: 3 coarse probes to find highest existing message ID
                step = 2000
                p_ids = [InputMessageID(id=i) for i in range(step, 100000, step)]
                res = await client(GetMessagesRequest(channel=entity, id=p_ids))
                max_found = max((m.id for m in res.messages if isinstance(m, Message)), default=0)

                f_ids = [InputMessageID(id=i) for i in range(max_found + 100, max_found + 2600, 100)]
                res2 = await client(GetMessagesRequest(channel=entity, id=f_ids))
                max_found = max([max_found] + [m.id for m in res2.messages if isinstance(m, Message)])

                e_ids = [InputMessageID(id=i) for i in range(max_found + 5, max_found + 155, 5)]
                res3 = await client(GetMessagesRequest(channel=entity, id=e_ids))
                max_found = max([max_found] + [m.id for m in res3.messages if isinstance(m, Message)])

                target_ids = [InputMessageID(id=i) for i in range(max(1, max_found - limit_per_channel * 3), max_found + 10)]
                res4 = await client(GetMessagesRequest(channel=entity, id=target_ids))
                msgs = [m for m in res4.messages if isinstance(m, Message) and m.message]
                if max_found > 0:
                    set_setting(f"tg_last_id:{ch}", str(max_found))
            else:
                # Incremental poll from last_id upwards
                poll_ids = [InputMessageID(id=i) for i in range(last_id + 1, last_id + 25)]
                res = await client(GetMessagesRequest(channel=entity, id=poll_ids))
                msgs = [m for m in res.messages if isinstance(m, Message) and m.message]
                if msgs:
                    new_max = max(m.id for m in msgs)
                    set_setting(f"tg_last_id:{ch}", str(new_max))

            msgs.sort(key=lambda x: x.id, reverse=True)
            ch_items = 0
            for m in msgs:
                if not m.message or len(m.message.strip()) < 30:
                    continue
                if m.date:
                    age = (now_utc - m.date).total_seconds()
                    if age > max_age_seconds:
                        continue
                if AD_PATTERNS.search(m.message):
                    continue

                lines = [l.strip() for l in m.message.split("\n") if l.strip()]
                raw_title = lines[0] if lines else f"Пост #{m.id}"
                raw_title = re.sub(r"^[⚡️🎬🛠🧠🚀💡🔥👀✴️•\s\-]+", "", raw_title).strip()
                if len(raw_title) > 100:
                    raw_title = raw_title[:97] + "..."

                items.append({
                    "id": f"tg_{ch}_{m.id}",
                    "title": f"[{ch}] {raw_title}",
                    "url": f"https://t.me/{ch}/{m.id}",
                    "source": f"tg/{ch}",
                    "content": m.message
                })
                ch_items += 1
                if ch_items >= limit_per_channel:
                    break

            await asyncio.sleep(0.3)
        except Exception as e:
            log.warning("Telegram channel crawl error for @%s: %s", ch, e)
            continue

    return items

