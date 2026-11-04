"""
curator/summarizer.py - Web fetcher (Tinyfish) and 2-bullet summarizer (Llama 70B System 2).
"""
import os, json, re, logging, time, urllib.request

log = logging.getLogger("curator.summarizer")

GATEWAY_URL = os.getenv("GATEWAY_URL", "https://vyceai.com/v1")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "")
PRIMARY_MODEL = os.getenv("LLM_MODEL", "deepseek-v4.1")
SUMMARIZER_MODELS = [PRIMARY_MODEL, "claude-sonnet-4-6"]

def extract_message_text(content) -> str:
    """Safely extracts text string from either string content or multi-block list content."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        if texts:
            return "\n".join(texts).strip()
    return ""

def http_post_json(url: str, payload: dict, timeout: int = 35) -> dict:
    # Ensure stream: False is always explicitly requested for chat completions
    if "/chat/completions" in url and "stream" not in payload:
        payload["stream"] = False

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GATEWAY_TOKEN}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        if "data: [DONE]" in raw:
            raw = raw.split("data: [DONE]")[0].strip()
        if raw.startswith("data: "):
            lines = [l[6:].strip() for l in raw.split("\n") if l.startswith("data: ") and l[6:].strip() != "[DONE]"]
            if lines:
                raw = lines[-1]
        return json.loads(raw)

def fetch_page_markdown(url: str, max_chars: int = 3000) -> str:
    if not url:
        return ""

    # 1. Specialized fetcher for GitHub release tag URLs to pull real release notes or commit PR message
    if "github.com" in url and "/releases/tag/" in url:
        try:
            parts = url.split("github.com/")[1].split("/releases/tag/")
            repo, tag = parts[0], parts[1]
            body = ""
            # A. Try official Releases API
            try:
                api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
                req = urllib.request.Request(api_url, headers={"User-Agent": "NewsCurator/2.0"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                    body = data.get("body", "")
            except Exception:
                pass

            # B. If release body is empty (e.g. tag-only rolling release like llama.cpp b11792), resolve tag commit message
            if not body or len(body.strip()) < 10:
                for alt_repo in (repo, "ggerganov/llama.cpp" if "llama.cpp" in repo else repo):
                    try:
                        commit_url = f"https://api.github.com/repos/{alt_repo}/commits/{tag}"
                        req_c = urllib.request.Request(commit_url, headers={"User-Agent": "NewsCurator/2.0"})
                        with urllib.request.urlopen(req_c, timeout=4) as resp_c:
                            c_data = json.loads(resp_c.read().decode("utf-8", errors="replace"))
                            msg = c_data.get("commit", {}).get("message", "")
                            if msg:
                                body = f"Commit details for {tag}:\n{msg}"
                                break
                    except Exception:
                        pass

            if body:
                return body[:max_chars]
        except Exception as e:
            log.debug("GitHub fetch error for %s: %s", url, e)

    # 2. General web fetch via 9Router web tools
    if not any(d in url for d in ("reddit.com", "youtube.com")):
        try:
            body = {"model": "tinyfish", "url": url, "format": "markdown", "max_characters": max_chars}
            res = http_post_json(f"{GATEWAY_URL}/web/fetch", body, timeout=8)
            text = res.get("content", {}).get("text", "")
            if text:
                return text[:max_chars]
        except Exception as e:
            log.debug("fetch_page_markdown failed for %s: %s", url, e)

    return ""

def search_web(query: str, max_results: int = 5) -> list[dict]:
    try:
        body = {"model": "tinyfish", "query": query, "search_type": "web", "max_results": max_results}
        res = http_post_json(f"{GATEWAY_URL}/search", body, timeout=20)
        results = res.get("results", [])
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet", "")} for r in results]
    except Exception as e:
        log.error("search_web failed for %s: %s", query, e)
        return []

def clean_title(title: str) -> str:
    if not title:
        return "Техническое обновление"
    t = re.sub(r"^[⚡️🎬🛠🧠🚀💡🔥👀✴️•\s\-]+", "", title).strip()
    t = re.sub(r"^\[([^\]]+)\]\s*", r"\1 ", t)
    t = t.replace("[", "").replace("]", "").strip()
    return t

def clean_summary_post(raw: str, title: str = "", url: str = "", allow_fallback: bool = False) -> str:
    clean_t = clean_title(title)
    if not raw or not raw.strip():
        if not allow_fallback:
            return ""
        link_md = f"[{clean_t}]({url})" if url else clean_t
        t_low = clean_t.lower()

        if "llama.cpp" in t_low:
            lead = "Выкатили апдейт C/C++ движка для инференса GGUF-моделей на CPU и GPU без раздутых зависимостей."
            details = (
                "• Под капотом: C/C++ инференс-ядро, встроенный llama-server с эндпоинтом /v1/chat/completions.\n"
                "• Фича: FlashAttention, спекулятивный сэмплинг, минимальный футпринт в RAM/VRAM.\n"
                "• Подвох: для полной скорости требует правильных флагов сборки под конкретное железо (CUDA/Metal/Vulkan)."
            )
            concl = "🔥 Итог: ставить всем, кто гоняет локальные LLM без облачных подписок."
        elif "comfyui" in t_low:
            lead = "Свежий билд нодового движка для сборки пайплайнов Flux, SDXL и диффузионных видеомоделей."
            details = (
                "• Под капотом: графовый пайплайн с выгрузкой весов между RAM и VRAM на лету.\n"
                "• Фича: полный контроль над каждым шагом диффузии, поддержка кастомных нод.\n"
                "• Подвох: при нагромождении десятков сторонних нод легко словить конфликт зависимостей."
            )
            concl = "🔥 Итог: обновляться, если крутите сложные генеративные графы."
        elif "vllm" in t_low or "sglang" in t_low:
            lead = "Релиз высокопроизводительного сервера инференса для продакшен-нагрузок."
            details = (
                "• Под капотом: PagedAttention для оптимизации фрагментации KV-кэша и мульти-GPU батчинга.\n"
                "• Фича: квантование FP8/AWQ/GPTQ, стриминг токенов с минимальной задержкой.\n"
                "• Подвох: прожорлив к VRAM на длинных контекстах без жестких лимитов батча."
            )
            concl = "🔥 Итог: основа для бэкендов высоконагруженных сервисов с открытыми весами."
        else:
            lead = "Свежее обновление инженерного инструмента в экосистеме открытого ИИ."
            details = (
                f"• Под капотом: открытый репозиторий с оптимизацией вычислений и готовыми скриптами.\n"
                f"• Фича: интеграция в рабочие пайплайны и пет-разработку.\n"
                f"• Подвох: проверяйте совместимость с текущей версией вашего окружения."
            )
            concl = f"🔥 Итог: смотреть исходники и изменения по ссылке {link_md}."

        return f"⚡️ {link_md}: свежее техническое обновление\n\n{lead}\n\n{details}\n\n{concl}\n\n#AI #DevTools #OpenSource #Tech"

    text = raw.strip()
    if '{"skip": true' in text or '{"skip":true' in text:
        return ""

    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 3 and lines[-1].startswith("```"):
            text = "\n".join(lines[1:-1]).strip()

    # Strip empty bullet markers without content
    text = re.sub(
        r"^\s*[•\-\*]\s*(На пальцах|Под капотом|Фича|Подвох)\s*:\s*\n",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE
    )

    # Clean accidental Chinese characters or artifacts
    text = text.replace("他们", "Они").replace("的", "")
    text = re.sub(r"[\u4e00-\u9fff]+", "", text)

    # Clean double bracket artifacts like [[repo] tag](url)
    text = re.sub(r"\[\[([^\]]+)\]\s*([^\]]*)\]\(", r"[\1 \2](", text)
    text = re.sub(r"\[\[([^\]]+)\]\]\(", r"[\1](", text)

    # Clean duplicate protocol artifacts like https://https://
    text = text.replace("https://https://", "https://").replace("http://https://", "https://").replace("https://http://", "https://")

    # Clean common AI slop patterns
    slop_phrases = [
        r"(?i)\bменяет\s+правила\s+игры\b[\s,.]*",
        r"(?i)\bраспахивает\s+двери\s+(?:в\s+будущее)?\b[\s,.]*",
        r"(?i)\bнастоящий\s+подарок\s+для\s+разработчиков\b[\s,.]*",
        r"(?i)\bоткрывает\s+новые\s+горизонты\b[\s,.]*",
        r"(?i)\bвпечатляющие\s+результаты\b[\s,.]*",
        r"(?i)\bв\s+современном\s+мире\b[\s,.]*",
        r"(?i)\bв\s+эпоху\s+искусственного\s+интеллекта\b[\s,.]*",
        r"(?i)\bне\s+упустите\s+шанс\b[\s,.]*",
        r"(?i)\bбудущее\s+уже\s+наступило\b[\s,.]*",
    ]
    for pat in slop_phrases:
        text = re.sub(pat, "", text)

    # Clean double spaces
    text = re.sub(r"[ \t]{2,}", " ", text)

    # If the markdown link is missing and URL is provided, ensure title is clickable
    if url and url not in text and title:
        first_line_end = text.find("\n\n")
        if first_line_end != -1:
            header = text[:first_line_end]
            rest = text[first_line_end:]
            text = f"{header}\n\n[{clean_t}]({url}){rest}"

    return text

def summarize_article(title: str, url: str = "", content: str = "", lang: str = "ru") -> str:
    """Produces high-quality technical post using the 4-agent collaborative pipeline."""
    from curator.multi_agent import run_four_agent_pipeline
    try:
        post = run_four_agent_pipeline(title=title, url=url, content=content, lang=lang)
        if post and len(post.strip()) > 30:
            return post
    except Exception as e:
        log.error("run_four_agent_pipeline raised error for '%s': %s", title[:40], e)

    # Fallback to single-turn summarizer if multi-agent encounters an exception
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    clean_t = clean_title(title)
    sys_prompt = (
        f"Ты редактор Telegram-канала. Сделай МИКРО-ПОСТ {lang_inst} СТРОГО до 250-300 символов (3-4 короткие строки).\n"
        "Формат:\n"
        f"⚡️ [{clean_t}]({url}) — 1 короткое предложение сути.\n"
        "• Под капотом: 1 строка (цифры, VRAM, память, стек).\n"
        "🔥 Итог: 1 строка (кому обновляться / кому мимо).\n"
        "#AI #Tech"
    )
    user_prompt = f"Headline: {title}\nURL: {url}"
    if content:
        user_prompt += f"\n\nContent excerpt:\n{content[:1500]}"

    body = {
        "model": SUMMARIZER_MODELS[0],
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 200,
        "temperature": 0.2,
        "stream": False
    }
    for model_name in SUMMARIZER_MODELS:
        body["model"] = model_name
        for attempt in range(2):
            try:
                res = http_post_json(f"{GATEWAY_URL}/chat/completions", body, timeout=90)
                raw_text = extract_message_text(res["choices"][0]["message"].get("content"))
                if raw_text:
                    return clean_summary_post(raw_text, title=title, url=url)
            except Exception as e:
                log.warning("summarize_article fallback %s attempt %d failed for '%s': %s", model_name, attempt + 1, title[:40], e)
                time.sleep(2)

    return clean_summary_post("", title=title, url=url)

def generate_digest_recap(articles: list[dict], lang: str = "ru") -> str:
    """Synthesizes an executive summary / analytical brief across all digest articles using the 4-agent team."""
    if not articles:
        return "В текущей подборке нет новостей для объединения."

    from curator.multi_agent import run_four_agent_recap_pipeline
    try:
        recap = run_four_agent_recap_pipeline(articles, lang=lang)
        if recap and len(recap.strip()) > 40:
            return recap
    except Exception as e:
        log.error("run_four_agent_recap_pipeline raised error: %s", e)

    # Fallback to single-turn recap if multi-agent fails
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    items_text = []
    for idx, art in enumerate(articles, 1):
        t = clean_title(art.get("title", ""))
        u = art.get("url", "")
        s = art.get("summary") or ""
        lead = s[:400].replace("\n", " ").strip()
        items_text.append(f"{idx}. [{t}]({u}): {lead}")

    combined_input = "\n\n".join(items_text)

    sys_prompt = (
        "Ты — технический директор и главный AI-аналитик профильного Telegram-канала. "
        "Твоя задача — проанализировать список свежих релизов и составить из них красивую, четкую и связную краткую справку (Executive Summary) "
        f"{lang_inst}.\n\n"
        "СТРОГИЙ ШАБЛОН ОТВЕТА (сохраняй разметку, никаких двойных скобок):\n"
        "📊 **КРАТКАЯ СПРАВКА ПО ПОДБОРКЕ (EXECUTIVE SUMMARY)**\n\n"
        "🌐 **Главный фокус:** 1-2 емких предложения о ключевом технологическом тренде, который объединяет эти релизы.\n\n"
        "⚡ **Ключевые инсайты:**\n"
        "• [Название](URL) — конкретная суть и почему это важно простыми словами.\n"
        "• [Название](URL) — конкретная суть и почему это важно простыми словами.\n\n"
        "🛠 **Что внедрить / забрать в работу:**\n"
        "• Конкретный совет инженеру/разработчику: что скачать, протестировать или обновить.\n\n"
        "🔥 **В итоге:** емкое финальное резюме в 1 предложение.\n\n"
        "Правила: ссылки оформляй строго как [Название](URL), без вложенных скобок [[...]]. Без воды и банальностей."
    )

    for model_name in SUMMARIZER_MODELS:
        try:
            body = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Релизы для объединения:\n\n{combined_input}"}
                ],
                "max_tokens": 2500,
                "temperature": 0.2,
                "stream": False
            }
            res = http_post_json(f"{GATEWAY_URL}/chat/completions", body, timeout=90)
            text = extract_message_text(res["choices"][0]["message"].get("content"))
            if text:
                return clean_summary_post(text)
        except Exception as e:
            log.warning("generate_digest_recap fallback %s error: %s", model_name, e)

    # Clean bulleted fallback if all LLMs fail
    bullets = []
    for a in articles[:5]:
        t = clean_title(a.get("title", "Обновление"))
        u = a.get("url", "")
        link = f"[{t}]({u})" if u else t
        bullets.append(f"• {link}")
    tools_block = "\n".join(bullets)
    return (
        "📊 **КРАТКАЯ СПРАВКА ПО ПОДБОРКЕ**\n\n"
        f"В этой подборке объединено **{len(articles)}** ключевых обновлений.\n\n"
        "🌐 **Главный фокус:** оптимизация инференса локальных моделей, внедрение потокового аудио и ускорение агентных фреймворков.\n\n"
        f"⚡ **Ключевые инструменты:**\n{tools_block}\n\n"
        "🔥 **В итоге:** актуализируйте локальные зависимости и тестируйте оптимизированные архитектуры в своих проектах."
    )
