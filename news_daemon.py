"""
news_daemon.py - Proactive Multi-Source News Curator & Scheduled Digest Bot.
Sources: Hacker News, Reddit, GitHub.
Filter & Evaluator: Llama 70B System 1 (AI, Models, Open-Source Dev Tools).
Content Enricher: Tinyfish Web Fetch & Search.
Post Generator: Llama 70B System 2 (Telegram Channel Rich Post with 🟢 specs & 🔥 conclusion).
Schedule: 08:00 and 20:00 MSK digests + on-demand /digest and /search.
Interactive UX: Per-item voting buttons & SQLite taste weight flywheel.
"""
import sys, os, asyncio, logging, datetime
from zoneinfo import ZoneInfo
if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

from telethon import TelegramClient, events, connection, Button

from curator.sources import fetch_all_sources, fetch_telegram_channels, CURATED_TG_CHANNELS
from curator.evaluator import classify_article, calculate_score
from curator.summarizer import fetch_page_markdown, summarize_article, search_web, generate_digest_recap
from curator.dedup import (
    find_duplicate,
    build_source_entry,
    merge_sources,
    format_discussion_line,
)
from curator.db import (
    init_db,
    save_article,
    get_unreported_high_signal,
    get_latest_high_signal,
    get_cluster_heads,
    update_cluster_sources,
    mark_articles_delivered,
    mark_cluster_delivered,
    record_user_vote,
    get_taste_weights,
    update_taste_weight,
    get_setting,
    set_setting,
    db_session
)
from curator.digest import build_digest, build_digest_posts

file_handler = logging.FileHandler("daemon.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

class FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

stderr_handler = FlushingStreamHandler(sys.stderr if sys.stderr is not None else open("daemon.err.log", "a", encoding="utf-8"))
stderr_handler.setLevel(logging.INFO)
stderr_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[file_handler, stderr_handler])
log = logging.getLogger("news_daemon")

TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = int(os.getenv("TG_CHAT_ID", "0"))
raw_allowed = os.getenv("ALLOWED_USERS", os.getenv("TG_OWNER_ID", str(TG_CHAT_ID)))
ALLOWED_USERS = {int(x.strip()) for x in raw_allowed.split(",") if x.strip().lstrip("-").isdigit() and int(x.strip()) != 0}
MTPROTO_PROXY = (
    os.getenv("PROXY_HOST", "192.168.1.1"),
    int(os.getenv("PROXY_PORT", "1443")),
    os.getenv("PROXY_SECRET", "")
)

MSK_TZ = ZoneInfo("Europe/Moscow")

def to_telethon_buttons(grid: list[list[dict]]) -> list[list[Button.inline]]:
    res = []
    for row in grid:
        res_row = []
        for btn in row:
            res_row.append(Button.inline(btn["text"], data=btn["data"].encode("utf-8")))
        res.append(res_row)
    return res

async def publish_to_channel(client: TelegramClient, greeting: str = "Свежая подборка AI & Dev релизов", limit: int = 5) -> tuple[bool, str]:
    target = get_setting("channel_target", "@eternalnnews")
    if not target or target.lower() == "off":
        return False, "Автопостинг в канал отключен."

    threshold = float(get_setting("threshold", "0.25"))
    candidates = get_unreported_high_signal(min_score=threshold, limit=limit)
    if not candidates:
        candidates = get_latest_high_signal(min_score=threshold, limit=limit)

    if not candidates:
        return False, "Нет подходящих новостей для публикации."

    lang = get_setting("lang", "ru")
    from curator.multi_agent import run_four_agent_digest_pipeline
    text = await asyncio.to_thread(run_four_agent_digest_pipeline, candidates, greeting, target, lang)
    if len(text) > 4000:
        text = text[:3950] + "\n\n_(сокращено)_"

    try:
        await client.send_message(target, text, link_preview=False)
        mark_articles_delivered([c["id"] for c in candidates])
        return True, f"Успешно опубликовано в {target}"
    except Exception as e:
        log.error("publish_to_channel failed: %s", e)
        return False, str(e)

async def publish_live_article(client: TelegramClient, article: dict):
    summary = article.get("summary")
    if not summary or any(stub in summary.lower() for stub in ("следите за обновлениями", "подробности доступны", "исходный код доступен")):
        lang = get_setting("lang", "ru")
        summary = await asyncio.to_thread(
            summarize_article,
            article.get("title", ""),
            article.get("url", ""),
            article.get("content", ""),
            lang
        )
        article["summary"] = summary

    if not summary or not client:
        return

    discussion = format_discussion_line(article.get("sources") or "[]")

    # 1. Publish to Channel @eternalnnews (clean, anonymous, no vote buttons)
    target = get_setting("channel_target", "@eternalnnews")
    if target and target.lower() != "off":
        try:
            ch_text = summary
            if discussion:
                ch_text += "\n" + discussion
            if target not in ch_text:
                ch_text += f"\n\n⚡ **Канал:** {target}"
            await client.send_message(target, ch_text, link_preview=False)
            log.info("Live article posted to channel %s: %s", target, article.get("title", "")[:40])
        except Exception as e:
            log.warning("Failed to live-post to channel %s: %s", target, e)

    # 2. Also send immediately to Admin PM with interactive vote buttons
    try:
        art_id = str(article.get("id", "live"))
        cb_id = art_id if len(art_id) <= 45 else str(abs(hash(art_id)))
        buttons = [
            [
                Button.inline("👍 Полезно", data=f"v:1:{cb_id}".encode()),
                Button.inline("👎 Шум", data=f"v:-1:{cb_id}".encode())
            ]
        ]
        pm_text = summary + ("\n" + discussion if discussion else "")
        await client.send_message(TG_CHAT_ID, pm_text, buttons=buttons, link_preview=False)
    except Exception as e:
        log.warning("Failed to send live article to admin: %s", e)

    mark_cluster_delivered(article.get("cluster_id") or article["id"])

async def send_digest_posts(client: TelegramClient, chat_id: int, greeting: str = "Сводка новостей", limit: int = 5):
    threshold = float(get_setting("threshold", "0.25"))
    candidates = get_unreported_high_signal(min_score=threshold, limit=limit)
    if not candidates:
        candidates = get_latest_high_signal(min_score=threshold, limit=limit)

    digest_format = get_setting("digest_format", "single")
    if digest_format == "multi":
        posts = await asyncio.to_thread(build_digest_posts, candidates, greeting=greeting)
        for text, button_grid in posts:
            buttons = to_telethon_buttons(button_grid) if button_grid else None
            await client.send_message(chat_id, text, buttons=buttons, link_preview=False)
            await asyncio.sleep(0.4)
    else:
        text, button_grid = await asyncio.to_thread(build_digest, candidates, greeting=greeting)
        buttons = to_telethon_buttons(button_grid) if button_grid else None
        await client.send_message(chat_id, text, buttons=buttons, link_preview=False)

    if candidates:
        mark_articles_delivered([c["id"] for c in candidates])

async def ingest_sweep(client: TelegramClient = None):
    log.info("Starting ingest sweep across sources...")
    with db_session() as conn:
        known_ids = {r["id"] for r in conn.execute("SELECT id FROM articles").fetchall()}

    # 1. Fetch Telegram channels (high priority)
    tg_items = []
    if client:
        try:
            tg_items = await fetch_telegram_channels(client, limit_per_channel=3)
            log.info("Telegram channels collected: %d items", len(tg_items))
        except Exception as e:
            log.warning("Telegram channel crawl failed: %s", e)

    # 2. Fetch web sources (HuggingFace, GitHub Releases, HN, Reddit)
    web_items = await asyncio.to_thread(fetch_all_sources, 20, 15)

    items = tg_items + web_items
    new_items = [it for it in items if it["id"] not in known_ids]
    log.info("Ingest: %d raw items collected (%d TG, %d Web), %d new to process",
             len(items), len(tg_items), len(web_items), len(new_items))

    weights = get_taste_weights()
    threshold = float(get_setting("threshold", "0.25"))
    lang = get_setting("lang", "ru")
    raw_topics = get_setting("active_topics", "all")
    active_topics = set(raw_topics.split(",")) if raw_topics and raw_topics != "all" else None
    raw_bl = get_setting("blacklist", "crypto,nft,airdrop,casino")
    blacklist = {b.strip().lower() for b in raw_bl.split(",") if b.strip()}

    processed = 0
    for it in new_items:
        metrics = await asyncio.to_thread(classify_article, it["title"], it.get("source", ""))
        score, matched = calculate_score(it["title"], metrics, weights, active_topics=active_topics, blacklist=blacklist)
        log.info("Item [%.2f] (%s): %s", score, metrics.get("category", "other"), it["title"][:50])

        # --- Event deduplication: same news from another source joins the existing cluster ---
        heads = get_cluster_heads(hours=72)
        dup = find_duplicate(heads, it["title"], it["url"])
        if dup:
            cluster_id = dup.get("cluster_id") or dup["id"]
            entry = build_source_entry(it["title"], it["url"], it.get("source", ""))
            merged = merge_sources(dup.get("sources") or "[]", entry)
            update_cluster_sources(cluster_id, merged)
            log.info("Duplicate of [%s] %s <- %s  (sources now: %s)",
                     cluster_id[:40], dup.get("title", "")[:40], it.get("source"), merged[:80])

            # A better-scored duplicate promotes itself to cluster head
            if score > float(dup.get("score") or 0) + 0.05 and score >= threshold:
                content = it.get("content") or await asyncio.to_thread(fetch_page_markdown, it["url"], 2500)
                summary = await asyncio.to_thread(summarize_article, it["title"], it["url"], content, lang)
                save_article({
                    "id": it["id"], "title": it["title"], "url": it["url"], "source": it["source"],
                    "signal": metrics["signal"], "fact": metrics["fact"], "hype": metrics["hype"],
                    "score": score, "category": metrics["category"], "summary": summary,
                    "cluster_id": it["id"], "sources": merged,
                })
                log.info("Promoted duplicate to cluster head: %s", it["title"][:40])
                await asyncio.sleep(2.0)
            else:
                save_article({
                    "id": it["id"], "title": it["title"], "url": it["url"], "source": it["source"],
                    "signal": metrics["signal"], "fact": metrics["fact"], "hype": metrics["hype"],
                    "score": score, "category": metrics["category"], "summary": None,
                    "cluster_id": cluster_id, "sources": "[]"
                })

            processed += 1
            await asyncio.sleep(0.5)
            continue

        summary = None
        if score >= threshold:
            content = it.get("content") or await asyncio.to_thread(fetch_page_markdown, it["url"], 2500)
            summary = await asyncio.to_thread(summarize_article, it["title"], it["url"], content, lang)
            log.info("Passed filter! Rich Telegram post generated for %s", it["title"][:40])
            await asyncio.sleep(2.0)

        art_record = {
            "id": it["id"],
            "title": it["title"],
            "url": it["url"],
            "source": it["source"],
            "signal": metrics["signal"],
            "fact": metrics["fact"],
            "hype": metrics["hype"],
            "score": score,
            "category": metrics["category"],
            "summary": summary,
            "cluster_id": it["id"],
            "sources": merge_sources("[]", build_source_entry(it["title"], it["url"], it.get("source", "")))
        }
        save_article(art_record)
        processed += 1

        # Real-time continuous delivery: if live mode is on and item passed filter
        delivery_mode = get_setting("delivery_mode", "live")
        if summary and delivery_mode == "live" and client:
            log.info("Live stream delivery for: %s", it["title"][:40])
            await publish_live_article(client, art_record)
            await asyncio.sleep(2.0)
        else:
            await asyncio.sleep(1.0)

    log.info("Ingest sweep completed: %d items evaluated and saved.", processed)
    return processed

async def background_ingester(client: TelegramClient):
    interval = int(os.getenv("INGEST_INTERVAL", "90"))
    while True:
        try:
            await ingest_sweep(client)
        except Exception as e:
            log.error("Ingester error: %s", e)
        await asyncio.sleep(interval)

AVAILABLE_TOPICS = {
    "models": "🧠 Модели и веса",
    "tools": "🛠 Dev Tools и движки",
    "free_api": "🔑 Free API и прокси",
    "local_ai": "💻 Локальный ИИ / GGUF",
    "agents": "🤖 ИИ-Агенты и RAG",
    "audio": "🎙 Голос, STT и TTS",
    "vision": "🎨 Видео и диффузия",
    "hardware": "⚡ Железо, GPU и чипы",
    "tech_news": "📡 IT-новости и софт",
}

def build_topics_view() -> tuple[str, list[list[Button.inline]]]:
    raw = get_setting("active_topics", "all")
    if raw == "all" or not raw:
        active = set(AVAILABLE_TOPICS.keys())
    else:
        active = set(raw.split(","))

    bl_raw = get_setting("blacklist", "crypto,nft,airdrop,casino")
    bl_list = [b.strip() for b in bl_raw.split(",") if b.strip()]

    text = (
        "🎯 **Настройка тем поиска и мониторинга:**\n\n"
        "Нажимайте кнопки с тумблерами, чтобы включать или отключать категории.\n"
        "Новости по отключенным категориям будут автоматически отсекаться AI-фильтром.\n\n"
        f"🚫 **Стоп-слова (Blacklist):** `{', '.join(bl_list) if bl_list else 'пусто'}`\n"
        "_Добавить стоп-слово:_ `/blacklist add <слово>`\n"
        "_Удалить:_ `/blacklist del <слово>`"
    )

    buttons = []
    row = []
    for top_key, top_name in AVAILABLE_TOPICS.items():
        is_on = top_key in active
        icon = "✅" if is_on else "❌"
        row.append(Button.inline(f"{icon} {top_name}", data=f"top:toggle:{top_key}".encode()))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        Button.inline("⚙️ Настройки", data=b"cmd:settings"),
        Button.inline("❌ Закрыть", data=b"set:close:x")
    ])
    return text, buttons

def build_settings_view() -> tuple[str, list[list[Button.inline]]]:
    threshold = float(get_setting("threshold", "0.25"))
    digest_limit = int(get_setting("digest_limit", "5"))
    schedule_mode = get_setting("schedule_mode", "2x")
    digest_format = get_setting("digest_format", "single")
    delivery_mode = get_setting("delivery_mode", "live")
    lang = get_setting("lang", "ru")
    ch_target = get_setting("channel_target", "@eternalnnews")

    th_label = "Баланс"
    if threshold <= 0.15:
        th_label = "Мягкий"
    elif threshold >= 0.35:
        th_label = "Строгий"

    sch_labels = {
        "2x": "08:00 и 20:00 МСК",
        "morning": "Утро (09:00 МСК)",
        "evening": "Вечер (20:00 МСК)",
        "4h": "Каждые 4 часа"
    }
    sch_label = sch_labels.get(schedule_mode, "08:00 и 20:00 МСК")
    fmt_label = "Одно сообщение" if digest_format == "single" else "Отдельные посты"
    del_label = "⚡ Live (сразу при выходе)" if delivery_mode == "live" else "📅 По расписанию"

    text = (
        "⚙️ **Панель управления куратором**\n\n"
        f"• **Режим доставки:** `{del_label}`\n"
        f"• **Формат дайджеста:** `{fmt_label}`\n"
        f"• **Порог качества:** `{threshold:.2f}` ({th_label})\n"
        f"• **Размер дайджеста:** `{digest_limit}` постов\n"
        f"• **Расписание сводок:** `{sch_label}`\n"
        f"• **Язык генерации:** `{lang.upper()}`\n"
        f"• **Канал трансляции:** `{ch_target}`\n\n"
        "_Нажимайте кнопки ниже, чтобы переключить параметры на лету:_"
    )

    def del_btn(mode: str, label: str):
        mark = "✓ " if delivery_mode == mode else ""
        return Button.inline(f"{mark}{label}", data=f"set:del:{mode}".encode("utf-8"))

    def fmt_btn(fmt: str, label: str):
        mark = "✓ " if digest_format == fmt else ""
        return Button.inline(f"{mark}{label}", data=f"set:fmt:{fmt}".encode("utf-8"))

    def th_btn(val: float, label: str):
        mark = "✓ " if abs(threshold - val) < 0.05 else ""
        return Button.inline(f"{mark}{label}", data=f"set:th:{val}".encode("utf-8"))

    def lim_btn(val: int):
        mark = "✓ " if digest_limit == val else ""
        suffix = "поста" if val in (2, 3, 4) else "постов"
        return Button.inline(f"{mark}{val} {suffix}", data=f"set:lim:{val}".encode("utf-8"))

    def sch_btn(mode: str, label: str):
        mark = "✓ " if schedule_mode == mode else ""
        return Button.inline(f"{mark}{label}", data=f"set:sch:{mode}".encode("utf-8"))

    def lang_btn(code: str, label: str):
        mark = "✓ " if lang == code else ""
        return Button.inline(f"{mark}{label}", data=f"set:lang:{code}".encode("utf-8"))

    buttons = [
        [del_btn("live", "⚡ Режим: Live (сразу)"), del_btn("scheduled", "📅 По расписанию")],
        [fmt_btn("single", "📜 Одно сообщение"), fmt_btn("multi", "📑 Отдельные посты")],
        [th_btn(0.15, "Мягкий 0.15"), th_btn(0.25, "Баланс 0.25"), th_btn(0.40, "Строгий 0.40")],
        [lim_btn(3), lim_btn(5), lim_btn(7)],
        [sch_btn("2x", "08:00 & 20:00"), sch_btn("morning", "Утро 09:00"), sch_btn("evening", "Вечер 20:00")],
        [sch_btn("4h", "Каждые 4ч"), lang_btn("ru", "🇷🇺 RU"), lang_btn("en", "🇬🇧 EN")],
        [
            Button.inline("🎯 Темы поиска", data=b"cmd:topics"),
            Button.inline(f"📡 Канал ({ch_target})", data=b"cmd:channel")
        ],
        [Button.inline("❌ Закрыть", data=b"set:close:x")]
    ]
    return text, buttons

async def background_scheduler(client: TelegramClient):
    last_sent_slot = None
    while True:
        try:
            now_msk = datetime.datetime.now(MSK_TZ)
            hour = now_msk.hour
            minute = now_msk.minute

            sch_mode = get_setting("schedule_mode", "2x")
            limit = int(get_setting("digest_limit", "5"))

            current_slot = None
            slot_name = ""
            if sch_mode == "2x":
                if hour == 8 and minute < 5:
                    current_slot = f"{now_msk.date()}_08"
                    slot_name = "Утренний дайджест (08:00 МСК)"
                elif hour == 20 and minute < 5:
                    current_slot = f"{now_msk.date()}_20"
                    slot_name = "Вечерний дайджест (20:00 МСК)"
            elif sch_mode == "morning":
                if hour == 9 and minute < 5:
                    current_slot = f"{now_msk.date()}_09"
                    slot_name = "Утренний дайджест (09:00 МСК)"
            elif sch_mode == "evening":
                if hour == 20 and minute < 5:
                    current_slot = f"{now_msk.date()}_20"
                    slot_name = "Вечерний дайджест (20:00 МСК)"
            elif sch_mode == "4h":
                if hour in (8, 12, 16, 20) and minute < 5:
                    current_slot = f"{now_msk.date()}_{hour}"
                    slot_name = f"Дайджест ({hour:02d}:00 МСК)"

            if current_slot and current_slot != last_sent_slot:
                log.info("Firing scheduled digest: %s (limit: %d)", slot_name, limit)
                # 1. Send personal digest to Admin PM
                await send_digest_posts(client, TG_CHAT_ID, greeting=slot_name, limit=limit)

                # 2. Autopilot broadcast to Telegram Channel (Mode B)
                target = get_setting("channel_target", "@eternalnnews")
                if target and target.lower() != "off":
                    ok, res = await publish_to_channel(client, greeting=slot_name, limit=limit)
                    if not ok:
                        log.warning("Channel auto-publish failed: %s", res)
                        await client.send_message(
                            TG_CHAT_ID,
                            f"⚠️ **Не удалось опубликовать дайджест в канал {target}:**\n`{res}`\n\n"
                            f"_Добавьте бота в канал администратором с правом публикации сообщений._"
                        )
                    else:
                        log.info("Successfully published scheduled digest to channel %s", target)

                last_sent_slot = current_slot
                log.info("Scheduled digest cycle completed.")

        except Exception as e:
            log.error("Scheduler error: %s", e)

        await asyncio.sleep(30)

def setup_bot_handlers(client: TelegramClient):
    @client.on(events.NewMessage(pattern=r"^/start"))
    async def cmd_start(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        threshold = get_setting("threshold", "0.25")
        lang = get_setting("lang", "ru")
        ch_target = get_setting("channel_target", "@eternalnnews")
        text = (
            "🤖 **AI & Dev News Curator**\n\n"
            "Автономный куратор открытых моделей, инструментов разработки и AI-релизов. "
            "Отслеживает Telegram-каналы, Hugging Face, GitHub Releases, Reddit и Hacker News. "
            "Фильтрует шум и оформляет посты с понятным объяснением сути, техническими фичами и пользой.\n\n"
            f"📅 **Режим доставки:**\n"
            f"• 🌅 Утренний дайджест: **08:00 МСК**\n"
            f"• 🌆 Вечерний дайджест: **20:00 МСК**\n"
            f"• 📡 Автопостинг в канал: `{ch_target}`\n"
            f"• ⚡ Порог отсева: `{threshold}` | Язык: `{lang}`\n\n"
            "Отправьте `/help` для полного списка команд и настроек."
        )
        quick_buttons = [
            [Button.inline("📰 Сводка сейчас", data=b"cmd:digest"), Button.inline("⚡ Краткая справка", data=b"cmd:recap")],
            [Button.inline("🎯 Темы поиска", data=b"cmd:topics"), Button.inline("⚙️ Настройки", data=b"cmd:settings")]
        ]
        await event.reply(text, buttons=quick_buttons)

    @client.on(events.NewMessage(pattern=r"^/help"))
    async def cmd_help(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        text = (
            "📖 **Справка по командам куратора:**\n\n"
            "📰 **Сводки и аналитика:**\n"
            "• `/digest` — прислать свежую подборку релизов в 1 сообщении\n"
            "• `/recap` — сформировать единую краткую справку (Executive Summary)\n"
            "• `/post_channel` — принудительно опубликовать дайджест в канал прямо сейчас\n\n"
            "🎯 **Темы и фильтрация:**\n"
            "• `/topics` — интерактивный выбор тем (тумблеры ✅ / ❌)\n"
            "• `/blacklist` — список запрещенных стоп-слов\n"
            "• `/blacklist add <слово>` — добавить слово в черный список\n"
            "• `/blacklist del <слово>` — удалить слово из черного списка\n"
            "• `/weights` — текущий профиль интересов и веса тем\n"
            "• `/set <тема> <вес>` — изменить приоритет темы (напр. `/set deepseek 1.5`)\n\n"
            "📡 **Канал и трансляция:**\n"
            "• `/channel` — статус привязанного Telegram-канала (@eternalnnews)\n"
            "• `/channel @имя_канала` — изменить канал для автопостинга\n"
            "• `/channel off` — отключить автопостинг в канал\n\n"
            "⚙️ **Настройки и поиск:**\n"
            "• `/settings` — интерактивная панель параметров (порог, размер, расписание, язык)\n"
            "• `/search <запрос>` — глубокий веб-поиск через Tinyfish\n"
            "• `/stats` — статистика базы и AI-отсева\n"
            "• `/sources` — список отслеживаемых каналов и репозиториев"
        )
        quick_buttons = [
            [Button.inline("📰 Сводка", data=b"cmd:digest"), Button.inline("⚡ Справка", data=b"cmd:recap")],
            [Button.inline("🎯 Темы", data=b"cmd:topics"), Button.inline("⚙️ Настройки", data=b"cmd:settings")]
        ]
        await event.reply(text, buttons=quick_buttons)

    @client.on(events.NewMessage(pattern=r"^/topics"))
    async def cmd_topics(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        text, buttons = build_topics_view()
        await event.reply(text, buttons=buttons)

    @client.on(events.NewMessage(pattern=r"^/blacklist(?:\s+(add|del|remove)\s+(.+))?"))
    async def cmd_blacklist(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        action = event.pattern_match.group(1)
        word = (event.pattern_match.group(2) or "").strip().lower()
        bl_raw = get_setting("blacklist", "crypto,nft,airdrop,casino")
        bl_set = {b.strip().lower() for b in bl_raw.split(",") if b.strip()}

        if not action:
            lines = [f"• `{w}`" for w in sorted(bl_set)]
            await event.reply(
                "🚫 **Черный список стоп-слов (Blacklist):**\n\n" +
                ("\n".join(lines) if lines else "_Список пуст_") +
                "\n\n_Добавить:_ `/blacklist add <слово>`\n_Удалить:_ `/blacklist del <слово>`"
            )
            return

        if action == "add":
            bl_set.add(word)
            set_setting("blacklist", ",".join(sorted(bl_set)))
            await event.reply(f"✅ Слово `{word}` добавлено в черный список.")
        elif action in ("del", "remove"):
            bl_set.discard(word)
            set_setting("blacklist", ",".join(sorted(bl_set)))
            await event.reply(f"✅ Слово `{word}` удалено из черного списка.")

    @client.on(events.NewMessage(pattern=r"^/channel(?:\s+(.+))?"))
    async def cmd_channel(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        arg = (event.pattern_match.group(1) or "").strip()
        if not arg:
            current = get_setting("channel_target", "@eternalnnews")
            btns = [
                [Button.inline("🚀 Опубликовать дайджест сейчас", data=b"cmd:post_channel")],
                [Button.inline("⚙️ В настройки", data=b"cmd:settings")]
            ]
            await event.reply(
                f"📡 **Канал трансляции:** `{current}`\n\n"
                f"Режим: **Автопилот (по расписанию и по запросу)**.\n"
                f"• Посты публикуются анонимно от лица канала.\n"
                f"• Изменить канал: `/channel @новое_имя`\n"
                f"• Отключить трансляцию: `/channel off`\n"
                f"• Принудительно выложить пост: `/post_channel`",
                buttons=btns
            )
            return

        if arg.lower() == "off":
            set_setting("channel_target", "off")
            await event.reply("✅ Автопостинг в канал **отключен**.")
        else:
            if not arg.startswith("@") and not arg.startswith("-100"):
                arg = "@" + arg
            set_setting("channel_target", arg)
            await event.reply(f"✅ Целевой канал трансляции установлен: **{arg}**\nУбедитесь, что бот добавлен в канал администратором с правом публикации сообщений.")

    @client.on(events.NewMessage(pattern=r"^/post_channel"))
    async def cmd_post_channel(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        target = get_setting("channel_target", "@eternalnnews")
        msg = await event.reply(f"⏳ Публикую актуальный дайджест в канал {target}...")
        ok, res_text = await publish_to_channel(client, greeting="Свежая подборка AI & Dev релизов")
        if ok:
            await msg.edit(f"✅ Дайджест успешно опубликован в канале {target}!")
        else:
            await msg.edit(f"❌ Ошибка публикации в {target}:\n`{res_text}`\n\nПроверьте, что бот добавлен администратором канала с правом «Публикация сообщений».")

    @client.on(events.NewMessage(pattern=r"^/settings"))
    async def cmd_settings(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        text, buttons = build_settings_view()
        await event.reply(text, buttons=buttons)

    @client.on(events.NewMessage(pattern=r"^/digest"))
    async def cmd_digest(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        limit = int(get_setting("digest_limit", "4"))
        msg = await event.reply("⏳ Формирую актуальную подборку AI-релизов...")
        await send_digest_posts(client, event.chat_id, greeting="Свежая подборка AI-релизов", limit=limit)
        await msg.delete()

    @client.on(events.NewMessage(pattern=r"^/recap"))
    async def cmd_recap(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        threshold = float(get_setting("threshold", "0.25"))
        limit = int(get_setting("digest_limit", "5"))
        lang = get_setting("lang", "ru")
        candidates = get_latest_high_signal(min_score=threshold, limit=limit)
        if not candidates:
            await event.reply("В базе пока нет новостей для объединения.")
            return

        status_msg = await event.reply("🧠 Перечитываю все новости подборки и составляю краткую справку...")
        recap_text = await asyncio.to_thread(generate_digest_recap, candidates, lang)
        close_btn = [[Button.inline("❌ Закрыть", data=b"set:close:x")]]
        await status_msg.edit(recap_text, buttons=close_btn, link_preview=False)

    @client.on(events.NewMessage(pattern=r"^/search\s+(.+)"))
    async def cmd_search(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        query = event.pattern_match.group(1).strip()
        msg = await event.reply(f"🔍 Ищу в сети через Tinyfish: _{query}_...")
        results = await asyncio.to_thread(search_web, query, 5)
        if not results:
            await msg.edit("❌ Поиск не вернул результатов.")
            return

        weights = get_taste_weights()
        lang = get_setting("lang", "ru")
        scored = []
        for r in results:
            m = await asyncio.to_thread(classify_article, r["title"])
            sc, _ = calculate_score(r["title"], m, weights)
            scored.append((sc, m, r))

        scored.sort(key=lambda x: -x[0])
        top_sc, top_m, top_r = scored[0]

        content = await asyncio.to_thread(fetch_page_markdown, top_r["url"], 2500)
        post_text = await asyncio.to_thread(summarize_article, top_r["title"], top_r["url"], content or top_r["snippet"], lang)

        search_id = f"search_{abs(hash(top_r['url']))}"
        buttons = [
            [
                Button.inline("👍 Полезно", data=f"v:1:{search_id}".encode()),
                Button.inline("👎 Шум", data=f"v:-1:{search_id}".encode())
            ]
        ]
        await msg.delete()
        await event.respond(post_text, buttons=buttons, link_preview=False)

    @client.on(events.NewMessage(pattern=r"^/sources"))
    async def cmd_sources(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        tg_lines = "\n".join(f"• @{ch}" for ch in CURATED_TG_CHANNELS)
        text = (
            "📡 **Активные источники мониторинга:**\n\n"
            "**Telegram-каналы:**\n"
            f"{tg_lines}\n\n"
            "**Открытые модели и чекпоинты:**\n"
            "• Hugging Face Trending Models (свежие веса, бенчмарки)\n\n"
            "**Инструменты и движки:**\n"
            "• GitHub Releases (ComfyUI, llama.cpp, vLLM, Ollama, SGLang, Transformers, LiteLLM)\n\n"
            "**Сообщества и анонсы:**\n"
            "• Reddit (r/LocalLLaMA, r/MachineLearning)\n"
            "• Hacker News (Show HN, AI/ML)\n\n"
            "**IT-медиа и порталы:**\n"
            "• Rozetked (новости и статьи)\n"
            "• Habr (хаб «Искусственный интеллект» и новости)\n"
            "• SecurityLab (кибербезопасность и AI-инциденты)\n"
            "• 3DNews (железо, чипы, AI-модели)"
        )
        await event.reply(text)

    @client.on(events.NewMessage(pattern=r"^/stats"))
    async def cmd_stats(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        with db_session() as conn:
            total = conn.execute("SELECT count(*) FROM articles").fetchone()[0]
            passed = conn.execute("SELECT count(*) FROM articles WHERE summary IS NOT NULL").fetchone()[0]
            delivered = conn.execute("SELECT count(*) FROM articles WHERE delivered_at IS NOT NULL").fetchone()[0]
            upvotes = conn.execute("SELECT count(*) FROM articles WHERE user_vote = 1").fetchone()[0]
            downvotes = conn.execute("SELECT count(*) FROM articles WHERE user_vote = -1").fetchone()[0]
        threshold = get_setting("threshold", "0.25")
        text = (
            f"📊 **Статистика куратора:**\n\n"
            f"• Всего просканировано: **{total}** новостей\n"
            f"• Прошло AI-фильтр: **{passed}** ({passed/total*100:.1f}%)" if total else ""
            f"\n• Доставлено в сводках: **{delivered}**\n"
            f"• Порог пропуска: `{threshold}`\n\n"
            f"🗳 **Обратная связь (Data Flywheel):**\n"
            f"• 👍 Одобрено: **{upvotes}**\n"
            f"• 👎 Отклонено: **{downvotes}**"
        )
        await event.reply(text)

    @client.on(events.NewMessage(pattern=r"^/weights"))
    async def cmd_weights(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        weights = get_taste_weights()
        lines = [f"• `{topic}`: **{w:.2f}**" for topic, w in sorted(weights.items(), key=lambda x: -x[1])]
        text = "🎯 **Taste Profile (веса тем):**\n\n" + "\n".join(lines) + "\n\n_Изменить: `/set <тема> <вес>`_"
        await event.reply(text)

    @client.on(events.NewMessage(pattern=r"^/set\s+(\w+)\s+([\d\.]+)"))
    async def cmd_set(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        topic = event.pattern_match.group(1).lower()
        val = float(event.pattern_match.group(2))
        update_taste_weight(topic, val)
        await event.reply(f"✅ Вес темы `{topic}` установлен на **{val:.2f}**")

    @client.on(events.NewMessage(pattern=r"^/threshold\s+([\d\.]+)"))
    async def cmd_threshold(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        val = float(event.pattern_match.group(1))
        set_setting("threshold", str(round(val, 2)))
        await event.reply(f"✅ Порог пропуска установлен на **{val:.2f}**")

    @client.on(events.NewMessage(pattern=r"^/lang\s+(ru|en)"))
    async def cmd_lang(event):
        if event.sender_id not in ALLOWED_USERS:
            return
        val = event.pattern_match.group(1).lower()
        set_setting("lang", val)
        await event.reply(f"✅ Язык постов переключён на: **{val.upper()}**")

    @client.on(events.CallbackQuery(pattern=rb"^cmd:(digest|stats|settings|recap|topics|channel|post_channel)"))
    async def on_quick_cmd(event):
        if event.sender_id not in ALLOWED_USERS:
            await event.answer("Доступ ограничен.", alert=True)
            return
        cmd = event.pattern_match.group(1).decode()
        if cmd == "recap":
            await event.answer("🧠 Составляю краткую справку по подборке...")
            threshold = float(get_setting("threshold", "0.25"))
            limit = int(get_setting("digest_limit", "5"))
            lang = get_setting("lang", "ru")
            candidates = get_latest_high_signal(min_score=threshold, limit=limit)
            if not candidates:
                await event.reply("В базе пока нет новостей для объединения.")
                return

            status_msg = await event.reply("🧠 Перечитываю все новости подборки и составляю краткую справку...")
            recap_text = await asyncio.to_thread(generate_digest_recap, candidates, lang)
            close_btn = [[Button.inline("❌ Закрыть", data=b"set:close:x")]]
            await status_msg.edit(recap_text, buttons=close_btn, link_preview=False)
        elif cmd == "digest":
            limit = int(get_setting("digest_limit", "4"))
            await event.answer("Отправляю свежие релизы...")
            await send_digest_posts(client, event.chat_id, greeting="Свежая подборка AI-релизов", limit=limit)
        elif cmd == "stats":
            await event.answer()
            with db_session() as conn:
                total = conn.execute("SELECT count(*) FROM articles").fetchone()[0]
                passed = conn.execute("SELECT count(*) FROM articles WHERE summary IS NOT NULL").fetchone()[0]
            await event.reply(f"📊 В базе: {total} новостей. Прошло AI-фильтр: {passed}.")
        elif cmd == "settings":
            await event.answer()
            text, buttons = build_settings_view()
            await event.respond(text, buttons=buttons)
        elif cmd == "topics":
            await event.answer()
            text, buttons = build_topics_view()
            await event.edit(text, buttons=buttons)
        elif cmd == "channel":
            await event.answer()
            target = get_setting("channel_target", "@eternalnnews")
            btns = [
                [Button.inline("🚀 Опубликовать дайджест сейчас", data=b"cmd:post_channel")],
                [Button.inline("⚙️ Настройки", data=b"cmd:settings"), Button.inline("❌ Закрыть", data=b"set:close:x")]
            ]
            await event.edit(
                f"📡 **Канал трансляции:** `{target}`\n\n"
                f"• Посты публикуются анонимно от лица канала.\n"
                f"• Изменить канал: `/channel @новое_имя`\n"
                f"• Отключить: `/channel off`\n"
                f"• Опубликовать прямо сейчас: `/post_channel`",
                buttons=btns
            )
        elif cmd == "post_channel":
            await event.answer("Публикую в канал...")
            target = get_setting("channel_target", "@eternalnnews")
            ok, res_text = await publish_to_channel(client, greeting="Свежая подборка AI & Dev релизов")
            if ok:
                await event.reply(f"✅ Дайджест успешно опубликован в канале {target}!")
            else:
                await event.reply(f"❌ Ошибка публикации в {target}:\n`{res_text}`")

    @client.on(events.CallbackQuery(pattern=rb"^top:toggle:(\w+)"))
    async def on_topic_toggle(event):
        if event.sender_id not in ALLOWED_USERS:
            await event.answer("Доступ ограничен.", alert=True)
            return
        top_key = event.pattern_match.group(1).decode()
        raw = get_setting("active_topics", "all")
        if raw == "all" or not raw:
            active = set(AVAILABLE_TOPICS.keys())
        else:
            active = set(raw.split(","))

        if top_key in active:
            active.discard(top_key)
        else:
            active.add(top_key)

        set_setting("active_topics", ",".join(sorted(active)) if active else "none")
        await event.answer(f"Тема {top_key}: {'Вкл' if top_key in active else 'Выкл'}")
        text, buttons = build_topics_view()
        await event.edit(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=rb"^set:(\w+):(.+)"))
    async def on_settings_click(event):
        if event.sender_id not in ALLOWED_USERS:
            await event.answer("Доступ ограничен.", alert=True)
            return
        action = event.pattern_match.group(1).decode()
        val = event.pattern_match.group(2).decode()

        if action == "del":
            set_setting("delivery_mode", val)
            label = "⚡ Live (сразу)" if val == "live" else "📅 По расписанию"
            await event.answer(f"Режим доставки: {label}")
        elif action == "th":
            new_th = str(round(float(val), 2))
            set_setting("threshold", new_th)
            await event.answer(f"Порог качества: {new_th}")
        elif action == "lim":
            new_lim = str(int(val))
            set_setting("digest_limit", new_lim)
            await event.answer(f"Размер дайджеста: {new_lim}")
        elif action == "sch":
            set_setting("schedule_mode", val)
            await event.answer("Расписание обновлено")
        elif action == "fmt":
            set_setting("digest_format", val)
            fmt_name = "Одно сообщение" if val == "single" else "Отдельные посты"
            await event.answer(f"Формат: {fmt_name}")
        elif action == "lang":
            set_setting("lang", val)
            await event.answer(f"Язык: {val.upper()}")
        elif action == "close":
            await event.delete()
            return

        text, buttons = build_settings_view()
        await event.edit(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=rb"^v:(-?\d+):(.+)"))
    async def on_vote(event):
        if event.sender_id not in ALLOWED_USERS:
            await event.answer("Доступ ограничен.", alert=True)
            return
        vote = int(event.pattern_match.group(1).decode())
        art_id = event.pattern_match.group(2).decode()

        title, adjusted = record_user_vote(art_id, vote)
        label = "👍 Одобрено" if vote > 0 else "👎 Шум"
        toast = f"Голос учтён: {label}."
        if adjusted:
            toast += f" Веса: {', '.join(adjusted)}"

        await event.answer(toast, alert=False)

        try:
            if event.message and event.message.buttons:
                updated_grid = []
                for row in event.message.buttons:
                    updated_row = []
                    for b in row:
                        b_data = b.data.decode("utf-8", errors="ignore") if b.data else ""
                        if b_data == f"v:1:{art_id}":
                            num = b.text.split()[-1] if " " in b.text else ""
                            updated_row.append(Button.inline(f"✓ {num}" if num else "✅ Полезно", data=b.data))
                        elif b_data == f"v:-1:{art_id}":
                            num = b.text.split()[-1] if " " in b.text else ""
                            updated_row.append(Button.inline(f"✗ {num}" if num else "❌ Шум", data=b.data))
                        else:
                            updated_row.append(b)
                    updated_grid.append(updated_row)
                await event.edit(buttons=updated_grid)
        except Exception as e:
            log.warning("Could not update keyboard: %s", e)

    @client.on(events.NewMessage)
    async def cmd_fallback(event):
        if event.out or event.sender_id not in ALLOWED_USERS:
            return
        if not event.raw_text or event.raw_text.startswith("/"):
            return
        log.info("Incoming plain message from user %s: %s", event.sender_id, event.raw_text)

        lowered = event.raw_text.lower()
        if any(w in lowered for w in ("объедини", "справка", "кратко", "итог", "recap", "summary")):
            await cmd_recap(event)
            return

        quick_buttons = [
            [Button.inline("📰 Сводка сейчас", data=b"cmd:digest"), Button.inline("⚡ Краткая справка", data=b"cmd:recap")],
            [Button.inline("🎯 Темы поиска", data=b"cmd:topics"), Button.inline("⚙️ Настройки", data=b"cmd:settings")]
        ]
        await event.reply(
            "👋 Бот на связи и мониторит ленты в реальном времени!\n\n"
            "• `/digest` — свежая подборка AI & Dev релизов единым постом.\n"
            "• `/recap` — объединить все новости в краткую справку (Executive Summary).\n"
            "• `/topics` — настройка тем мониторинга тумблерами.\n"
            "• `/channel` — статус и управление публикацией в канал.\n"
            "• `/help` — полный список всех команд бота.",
            buttons=quick_buttons
        )

async def main():
    init_db()
    client = TelegramClient(
        "bot_session",
        TG_API_ID,
        TG_API_HASH,
        connection=connection.ConnectionTcpMTProxyRandomizedIntermediate,
        proxy=MTPROTO_PROXY
    )
    setup_bot_handlers(client)
    await client.start(bot_token=TG_BOT_TOKEN)
    log.info("Bot started successfully. Launching background ingester and scheduler...")

    if "--once" in sys.argv:
        log.info("Executing single test sweep...")
        await ingest_sweep(client)
        await client.disconnect()
        return

    asyncio.create_task(background_ingester(client))
    asyncio.create_task(background_scheduler(client))
    log.info("All background tasks running. Entering event loop...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
