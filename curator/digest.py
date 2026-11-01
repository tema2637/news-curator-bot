"""
curator/digest.py - Formatter for rich Telegram channel-style AI posts and digests.
"""
import logging, re

from curator.dedup import format_discussion_line

log = logging.getLogger("curator.digest")

def format_single_post(item: dict) -> tuple[str, list[list[dict]]]:
    title = item.get("title", "")
    url = item.get("url", "")
    summary = item.get("summary")
    if not summary:
        summary = f"💡 **{title.upper()}**\n\n[{title}]({url}) — подробности релиза по ссылке.\n\n🟢 Подробности доступны в первоисточнике.\n\n🔥 В итоге: следите за обновлениями."

    discussion = format_discussion_line(item.get("sources") or "")
    if discussion:
        summary += "\n" + discussion

    user_vote = int(item.get("user_vote", 0))
    item_id = str(item.get("id", "post"))

    up_label = "✅ Полезно" if user_vote == 1 else "👍 Полезно"
    down_label = "❌ Шум" if user_vote == -1 else "👎 Шум"
    cb_id = item_id if len(item_id) <= 45 else str(abs(hash(item_id)))

    buttons = [
        [
            {"text": up_label, "data": f"v:1:{cb_id}"},
            {"text": down_label, "data": f"v:-1:{cb_id}"}
        ]
    ]
    return summary, buttons

def extract_digest_item(item: dict, idx: int) -> str:
    digits = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    num_emoji = digits[idx - 1] if 1 <= idx <= 10 else f"{idx}."

    title = item.get("title", "")
    url = item.get("url", "")
    summary = item.get("summary") or ""

    clean_title = re.sub(r"^[⚡️🎬🛠🧠🚀💡🔥👀✴️•\s\-]+", "", title).strip()
    clean_title = re.sub(r"^\[([^\]]+)\]\s*", r"\1 ", clean_title).replace("[", "").replace("]", "").strip()
    if clean_title.isupper():
        clean_title = clean_title.capitalize()

    # Match existing markdown link or fallback to title
    link_match = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", summary)
    link_url = link_match.group(2) if link_match else url
    link_text = link_match.group(1) if link_match else clean_title
    link_text = re.sub(r"^\[([^\]]+)\]\s*", r"\1 ", link_text).replace("[", "").replace("]", "").strip()

    lines = [l.strip() for l in summary.split("\n") if l.strip()]
    bullets = []
    for l in lines:
        if l.startswith("🟢") or l.startswith("•"):
            b_text = l.lstrip("🟢• ").strip()
            # Ignore lazy placeholders
            if any(p in b_text.lower() for p in ("подробности доступны", "исходный код доступен", "следите за обновлениями")):
                continue
            if len(b_text) > 170:
                b_text = b_text[:167] + "..."
            bullets.append(f"  • {b_text}")
            if len(bullets) >= 2:
                break

    if not bullets:
        for l in lines[1:]:
            if not l.startswith("🔥") and not l.startswith("#") and not l.startswith("💡") and len(l) > 25:
                if any(p in l.lower() for p in ("подробности доступны", "следите за обновлениями")):
                    continue
                bullets.append(f"  • {l[:170]}...")
                if len(bullets) >= 2:
                    break

    if not bullets:
        bullets.append("  • Открытый релиз с оптимизациями архитектуры и новыми возможностями.")

    result = f"{num_emoji} **[{link_text}]({link_url})**\n" + "\n".join(bullets)

    discussion = format_discussion_line(item.get("sources") or "")
    if discussion:
        result += "\n" + discussion

    return result

def build_digest_posts(articles: list[dict], greeting: str = "Сводка новостей") -> list[tuple[str, list[list[dict]]]]:
    if not articles:
        return [(f"📰 **{greeting}**\n\nЗа прошедший период не найдено важных AI-обновлений, пробивших фильтр качества.", [])]

    posts = []
    recap_btns = [[{"text": "⚡ Объединить все новости", "data": "cmd:recap"}]] if articles else []
    banner = f"📰 **{greeting}**\n\nОтобрано **{len(articles)}** ключевых AI-релизов:"
    posts.append((banner, recap_btns))

    for item in articles:
        posts.append(format_single_post(item))

    return posts

def build_digest(articles: list[dict], greeting: str = "Сводка новостей") -> tuple[str, list[list[dict]]]:
    if not articles:
        return f"📰 **{greeting}**\n\nЗа прошедший период не найдено важных обновлений, пробивших фильтр качества.", []

    body_blocks = [extract_digest_item(item, idx) for idx, item in enumerate(articles, 1)]
    text = (
        f"📰 **{greeting}**\n\n"
        f"Отобрано **{len(articles)}** ключевых AI & Dev релизов:\n\n" +
        "\n\n".join(body_blocks) +
        "\n\n🔥 **В итоге:** голосуйте кнопками ниже, чтобы бот обучал матрицу вкуса под вас."
    )

    up_row = []
    down_row = []
    for idx, item in enumerate(articles, 1):
        item_id = str(item.get("id", "post"))
        cb_id = item_id if len(item_id) <= 45 else str(abs(hash(item_id)))
        u_vote = int(item.get("user_vote", 0))

        up_lbl = f"✓ {idx}" if u_vote == 1 else f"👍 {idx}"
        down_lbl = f"✗ {idx}" if u_vote == -1 else f"👎 {idx}"
        up_row.append({"text": up_lbl, "data": f"v:1:{cb_id}"})
        down_row.append({"text": down_lbl, "data": f"v:-1:{cb_id}"})

    button_grid = []
    # In Telegram clients, max 4 buttons per row prevents squashing on small screens
    chunk_size = 4
    for i in range(0, len(up_row), chunk_size):
        button_grid.append(up_row[i:i + chunk_size])
    for i in range(0, len(down_row), chunk_size):
        button_grid.append(down_row[i:i + chunk_size])

    if articles:
        button_grid.append([
            {"text": "⚡ Объединить все новости", "data": "cmd:recap"}
        ])

    if len(text) > 4000:
        text = text[:3950] + "\n\n_(сокращено)_"
    return text, button_grid
