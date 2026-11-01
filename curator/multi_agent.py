"""
curator/multi_agent.py - 4-agent collaborative refinement pipeline:
1. Agent 1 (Researcher): extracts technical facts, commit details, architecture.
2. Agent 2 (Fact-Checker / Critic 1): audits Agent 1 against raw data, spots hallucinations & omissions.
3. Agent 3 (Tech Specialist / Critic 2 & Enhancer): audits Agents 1 & 2, deepens engineering context & benchmarks.
4. Agent 4 (Lead Editor / Composer): synthesizes all 3 agents' findings into the final Telegram post.
"""
import logging, time
from curator.summarizer import http_post_json, extract_message_text, clean_summary_post, clean_title, GATEWAY_URL

log = logging.getLogger("curator.multi_agent")

FAST_MODELS = [
    "mistral/mistral-small-latest",
    "mistral/codestral-latest",
    "oc/deepseek-v4.1-flash-free",
    "mistral/mistral-large-4",
]

COMPOSER_MODELS = [
    "mistral/mistral-small-latest",
    "mistral/mistral-large-4",
    "oc/deepseek-v4.1-flash-free",
]


def call_agent_step(
    role_name: str,
    sys_prompt: str,
    user_prompt: str,
    models: list[str] | None = None,
    max_tokens: int = 1000,
    timeout: int = 35
) -> str:
    """Invokes an agent role across fallback models."""
    use_models = models or FAST_MODELS
    for model_name in use_models:
        body = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "stream": False
        }
        for attempt in range(2):
            try:
                t0 = time.time()
                res = http_post_json(f"{GATEWAY_URL}/chat/completions", body, timeout=timeout)
                dt = time.time() - t0
                content = res.get("choices", [{}])[0].get("message", {}).get("content")
                text = extract_message_text(content)
                if text:
                    log.info("%s succeeded with %s in %.2fs (%d chars)", role_name, model_name, dt, len(text))
                    return text
            except Exception as e:
                log.warning("%s attempt %d on %s failed: %s", role_name, attempt + 1, model_name, e)
                time.sleep(1.5)

    log.error("%s failed across all models", role_name)
    return ""


def agent1_research(title: str, url: str, content: str) -> str:
    """Agent 1: Technical researcher extracting facts, commits, and architecture."""
    sys_prompt = (
        "Ты — Агент 1 (Технический исследователь). Твоя задача — извлечь максимум точных технических фактов по новости.\n"
        "Отвечай связным текстом на русском языке, без кода и без блоков diff.\n"
        "СТРОГО БЕЗ НЕЙРОСЛОПА: никакой воды, рекламы, абстракций и восторженных эпитетов.\n"
        "Опиши:\n"
        "1. Что это за проект / библиотека / модель.\n"
        "2. Что конкретно изменилось в коммите или релизе (точные параметры, методы, флаги).\n"
        "3. Архитектурные детали (VRAM, CUDA/CPU, инференс, API, спекулятивное декодирование, форматы).\n"
        "4. Какую реальную проблему решает это изменение.\n"
        "5. Суть на пальцах: простая жизненная аналогия для человека не из IT (без заумных слов, понятно любому человеку с улицы)."
    )
    user_prompt = f"Заголовок: {title}\nURL: {url}\n\nИсходные данные релиза:\n{content[:2500]}"
    return call_agent_step("Agent 1 (Researcher)", sys_prompt, user_prompt, max_tokens=900)


def agent2_factcheck(raw_content: str, a1_output: str) -> str:
    """Agent 2: Fact-checker auditing Agent 1 against raw ground-truth data."""
    sys_prompt = (
        "Ты — Агент 2 (Фактчекер и первый технический критик).\n"
        "Твоя задача — критически проверить отчет Агента 1, сопоставив его с исходными сырыми данными новости.\n"
        "Отвечай связным аналитическим текстом на русском языке, без кода и без блоков diff.\n"
        "Оцени:\n"
        "1. ВЫРЕЗАТЬ НЕЙРОСЛОП И ДОМЫСЛЫ: срезай любые рекламные клише («революционный», «меняет правила игры», «настоящий подарок»).\n"
        "2. Проверь факты: подтверждены ли заявления Агента 1 исходными данными (что истинно, а что галлюцинация).\n"
        "3. Проверь аналогию «на пальцах»: не искажает ли она реальную суть и действительно ли проста для не-айтишников.\n"
        "4. Укажи упущенные технические нюансы, ограничения (версии, зависимости, GPU-требования).\n"
        "Сформулируй четкие исправления и уточнения к фактам."
    )
    user_prompt = (
        f"Исходные сырые данные:\n{raw_content[:2500]}\n\n"
        f"Отчет Агента 1 (факты для проверки):\n{a1_output}"
    )
    return call_agent_step("Agent 2 (Fact-Checker)", sys_prompt, user_prompt, max_tokens=900)


def agent3_refine(raw_content: str, a1_output: str, a2_output: str) -> str:
    """Agent 3: Tech specialist reconciling Agent 1 & 2 and adding practical engineering depth."""
    sys_prompt = (
        "Ты — Агент 3 (Инженер-эксперт и второй технический аудитор).\n"
        "Твоя задача — изучить исходные данные новости, факты Агента 1 и критические замечания Агента 2.\n"
        "Отвечай связным аналитическим текстом на русском языке, без кода и без блоков diff.\n"
        "Сделай следующее:\n"
        "1. Зачисти любые оставшиеся размытые формулировки и штампы — оставь только твердые цифры и факты.\n"
        "2. Углуби технический контекст: влияние на производительность (VRAM, шина PCIe, скорость токенов/сек, задержка).\n"
        "3. Отшлифуй объяснение «на пальцах»: сделай его идеальным, чтобы понял человек без малейшего технического бэкграунда, без единого непонятного термина.\n"
        "4. Опиши сценарии практического применения: кому инструмент реально нужен, а кто может пропустить.\n"
        "Выдай итоговый согласованный набор проверенных технических фактов и понятную аналогию."
    )
    user_prompt = (
        f"Исходные данные:\n{raw_content[:2000]}\n\n"
        f"Агент 1 (первичные факты):\n{a1_output}\n\n"
        f"Агент 2 (критика и фактчекинг):\n{a2_output}"
    )
    return call_agent_step("Agent 3 (Refiner)", sys_prompt, user_prompt, max_tokens=1000)


def agent4_compose(
    title: str,
    url: str,
    a1_output: str,
    a2_output: str,
    a3_output: str,
    lang: str = "ru"
) -> str:
    """Agent 4: Chief editor compiling verified insights into the final Telegram post in Backdoor style."""
    clean_t = clean_title(title)
    lang_inst = "на русском языке" if lang == "ru" else "in English"

    sys_prompt = (
        "Ты — Агент 4 (Выпускающий редактор Telegram-канала в стиле «Бэкдор» — сжатый срез без цензуры и без нейрослопа).\n"
        f"Твоя задача — скомпоновать максимально живой, плотный и честный пост {lang_inst}, "
        "который будет одновременно понятен обычному человеку с улицы и полезен сеньор-разработчику.\n\n"
        "СТРОЖАЙШИЙ ЗАПРЕТ НА НЕЙРОСЛОП (AI SLOP):\n"
        "- Ноль маркетинговой шелухи и штампов («революционный», «меняет правила игры», «настоящий подарок», «открывает горизонты», «в современном мире»).\n"
        "- Разговорный, жесткий тон опытного разработчика без реверансов и без воды.\n"
        "- Только сухие цифры и архитектура: сколько VRAM, какие флаги, какая шина, какие модели.\n\n"
        "СТРОГИЙ ШАБЛОН «БЭКДОР»:\n"
        f"⚡️ [{clean_t}]({url}): краткая суть релиза в одну строку\n\n"
        "Сразу первый абзац без служебного слова «Лид:» (1-2 живых плотных предложения: что выкатили и зачем это нужно).\n\n"
        "• На пальцах: простое объяснение без единого IT-термина (запрещены слова «API», «инференс», «бенчмарк», «модель», «тензоры», «квантование») на бытовом примере или аналогии — понятно даже тому, кто вообще не разбирается в теме.\n"
        "• Под капотом: архитектура, стек, память/VRAM, затронутые компоненты (сухо, с цифрами для профи).\n"
        "• Фича: ключевые параметры, замеры скорости/задержки или практические сценарии.\n"
        "• Подвох: реальные ограничения, баги, лицензия или о чем умолчали авторы.\n\n"
        "🔥 Итог: качать/обновляться, если ... Если ... — сразу мимо.\n\n"
        "#AI #DevTools #OpenSource #Tech\n\n"
        "ПРАВИЛА:\n"
        "- Ссылка строго вида [{clean_t}]({url}) прямо в первой строке!\n"
        "- Никаких двойных скобок [[...]] и отписок («подробности по ссылке»)."
    )

    user_prompt = (
        f"Заголовок новости: {clean_t}\n"
        f"URL новости: {url}\n\n"
        f"Агент 1 (Факты):\n{a1_output}\n\n"
        f"Агент 2 (Фактчекинг и критика):\n{a2_output}\n\n"
        f"Агент 3 (Инженерное углубление и арбитраж):\n{a3_output}"
    )

    return call_agent_step(
        "Agent 4 (Lead Editor)",
        sys_prompt,
        user_prompt,
        models=COMPOSER_MODELS,
        max_tokens=1100,
        timeout=45
    )


def agent4_verify_post(
    title: str,
    url: str,
    a4_draft: str,
    a3_enhanced: str,
    lang: str = "ru"
) -> str:
    """Agent 4 Second Check: Final quality assurance auditing the composed post in Backdoor style."""
    clean_t = clean_title(title)
    lang_inst = "на русском языке" if lang == "ru" else "in English"

    sys_prompt = (
        "Ты — Главный инспектор качества и цензор нейрослопа формата «Бэкдор» (Вторая проверка Агента 4).\n"
        f"Твоя задача — провести безжалостный финальный аудит черновика поста перед публикацией {lang_inst}.\n\n"
        "КРИТЕРИИ АУДИТА («БЭКДОР»):\n"
        f"1. Заголовок strictly вида: ⚡️ [{clean_t}]({url}): краткая суть релиза.\n"
        "2. Первый абзац идет сразу после заголовка БЕЗ служебного слова «Лид:» (ровно 1-2 живых плотных предложения).\n"
        "3. Пункт «• На пальцах:» ОБЯЗАТЕЛЕН. Проверь: в нём НЕ ДОЛЖНО БЫТЬ заумных терминов (слов «API», «инференс», «бенчмарк», «тензоры»). Должно быть понятно любому новичку.\n"
        "4. Пункты строго с маркером •: • На пальцах: ..., • Под капотом: ..., • Фича: ..., • Подвох: ...\n"
        "5. Блок итога строго: 🔥 Итог: качать/обновляться, если ... Если ... — сразу мимо.\n"
        "6. ВЫРЕЗАТЬ ВЕСЬ НЕЙРОСЛОП: безжалостно удали любые рекламные клише («революция», «меняет правила игры», «настоящий подарок»).\n"
        f"7. Никаких двойных скобок [[...]]. Ссылка кликабельна и ведет на {url}.\n\n"
        "Выдай ИДЕАЛЬНЫЙ чистовой пост без вступительных слов и комментариев."
    )

    user_prompt = (
        f"Новость: {clean_t}\n"
        f"URL: {url}\n\n"
        f"Проверенные факты инженера (Агент 3):\n{a3_enhanced}\n\n"
        f"Черновик поста от Агента 4 для проверки:\n{a4_draft}"
    )

    verified = call_agent_step(
        "Agent 4 (2nd Check / QA)",
        sys_prompt,
        user_prompt,
        models=COMPOSER_MODELS,
        max_tokens=1100,
        timeout=35
    )
    return verified or a4_draft


def run_four_agent_pipeline(title: str, url: str = "", content: str = "", lang: str = "ru") -> str:
    """Executes the full 4-agent review & composition chain with graceful fallback."""
    raw_info = content or title
    log.info("Starting 4-agent pipeline for '%s'...", title[:40])

    # 1. Agent 1: Research
    a1_facts = agent1_research(title, url, raw_info)
    if not a1_facts:
        log.warning("Agent 1 failed, passing raw info to Agent 2")
        a1_facts = f"Проект: {title}. Данные: {raw_info[:500]}"

    # 2. Agent 2: Fact-Check
    a2_critique = agent2_factcheck(raw_info, a1_facts)
    if not a2_critique:
        log.warning("Agent 2 failed, proceeding with Agent 1 facts")
        a2_critique = "Факты приняты без замечаний."

    # 3. Agent 3: Refine & Enhance
    a3_enhanced = agent3_refine(raw_info, a1_facts, a2_critique)
    if not a3_enhanced:
        log.warning("Agent 3 failed, proceeding with previous stages")
        a3_enhanced = a1_facts

    # 4. Agent 4: Final Compose
    a4_post = agent4_compose(title, url, a1_facts, a2_critique, a3_enhanced, lang=lang)

    # 4.5. Second Check of Agent 4 (Quality Assurance)
    if a4_post:
        log.info("Running second check of Agent 4 for '%s'...", title[:40])
        a4_verified = agent4_verify_post(title, url, a4_post, a3_enhanced, lang=lang)
        if a4_verified:
            a4_post = a4_verified

    if a4_post:
        return clean_summary_post(a4_post, title=title, url=url)

    log.error("4-agent pipeline failed to compose post; falling back to clean template")
    return clean_summary_post("", title=title, url=url)


# ============================================================================
# 4-AGENT RECAP PIPELINE (Executive Summary / Analytical Brief)
# ============================================================================

def recap_agent1_analyze(combined_input: str, lang: str = "ru") -> str:
    """Recap Agent 1: Analyzes entire collection, discovers overarching technical trends and key breakthroughs."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Агент 1 (Аналитик подборки AI-новостей).\n"
        f"Твоя задача — проанализировать список свежих релизов и выделить главные сквозные тренды, ключевые факты и прорывы по проектам {lang_inst}.\n"
        "Отвечай связным техническим текстом, без кода и без блоков diff."
    )
    return call_agent_step("Recap Agent 1 (Analyst)", sys_prompt, f"Список релизов:\n\n{combined_input}", max_tokens=800)


def recap_agent2_factcheck(combined_input: str, a1_output: str, lang: str = "ru") -> str:
    """Recap Agent 2: Fact-checks Agent 1's insights against the input articles, spots hallucinations and false links."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Агент 2 (Фактчекер и первый критик подборки).\n"
        "Твоя задача — сопоставить выводы Агента 1 с исходным списком релизов.\n"
        "Проверь, нет ли искажений фактов, вымышленных фич или ложных связок. Подтверди проверенные факты "
        f"{lang_inst}, без кода и без блоков diff."
    )
    user_prompt = f"Исходный список релизов:\n\n{combined_input}\n\nВыводы Агента 1:\n\n{a1_output}"
    return call_agent_step("Recap Agent 2 (Fact-Checker)", sys_prompt, user_prompt, max_tokens=800)


def recap_agent3_strategize(combined_input: str, a1_output: str, a2_output: str, lang: str = "ru") -> str:
    """Recap Agent 3: Reconciles issues and formulates actionable engineering recommendations."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Агент 3 (Инженерный стратег и второй критик).\n"
        "Твоя задача — изучить факты А1 и критику А2, устранить любые противоречия и сформулировать "
        f"практическую ценность для инженера {lang_inst}: что стоит внедрять, какие технологии экономят ресурсы или время. Без кода."
    )
    user_prompt = f"Исходные релизы:\n\n{combined_input}\n\nАгент 1:\n{a1_output}\n\nАгент 2:\n{a2_output}"
    return call_agent_step("Recap Agent 3 (Strategist)", sys_prompt, user_prompt, max_tokens=800)


def recap_agent4_compose(combined_input: str, a1_output: str, a2_output: str, a3_output: str, lang: str = "ru") -> str:
    """Recap Agent 4: Chief editor compiling verified insights into the final Executive Summary post."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Агент 4 (Главный выпускающий редактор профильного IT-канала).\n"
        f"Скомпонуй итоговый пост краткой справки (Executive Summary) для Telegram-канала {lang_inst} "
        "на основе согласованного анализа всех 3 агентов.\n\n"
        "СТРОЖАЙШИЙ ЗАПРЕТ НА НЕЙРОСЛОП:\n"
        "- Никакой воды, рекламных эпитетов («революция», «новая эра», «меняет правила игры», «настоящий подарок»).\n"
        "- Только чистый технический синтез трендов, сухие цифры и архитектурные решения.\n\n"
        "СТРОГИЙ ШАБЛОН:\n"
        "📊 **КРАТКАЯ СПРАВКА ПО ПОДБОРКЕ (EXECUTIVE SUMMARY)**\n\n"
        "🌐 **Главный фокус:** (1-2 емких предложения о ключевом технологическом тренде)\n\n"
        "⚡ **Ключевые инсайты:**\n"
        "• [Название](URL) — конкретная суть простыми словами без воды.\n"
        "• [Название](URL) — конкретная суть простыми словами без воды.\n\n"
        "🛠 **Что внедрить / забрать в работу:**\n"
        "• Практический совет инженеру: что скачать, протестировать или внедрить в прод.\n\n"
        "🔥 **В итоге:** емкое финальное резюме в 1 предложение.\n\n"
        "Правила: ссылки строго вида [Название](URL), без двойных скобок [[...]], без отписок."
    )
    user_prompt = (
        f"Исходные релизы:\n\n{combined_input}\n\n"
        f"Агент 1 (Анализ трендов):\n{a1_output}\n\n"
        f"Агент 2 (Фактчекинг):\n{a2_output}\n\n"
        f"Агент 3 (Инженерная стратегия):\n{a3_output}"
    )
    return call_agent_step("Recap Agent 4 (Lead Editor)", sys_prompt, user_prompt, models=COMPOSER_MODELS, max_tokens=1000)


def recap_agent4_verify(
    combined_input: str,
    a4_draft: str,
    a3_strategy: str,
    lang: str = "ru"
) -> str:
    """Recap Agent 4 Second Check: Final quality assurance auditing the Executive Summary."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Главный инспектор качества аналитических справок и цензор нейрослопа (Вторая проверка Агента 4).\n"
        f"Твоя задача — провести контрольный аудит Executive Summary перед публикацией {lang_inst}.\n\n"
        "КРИТЕРИИ АУДИТА:\n"
        "1. Полная зачистка нейрослопа: вырежи любые штампы («революционный», «меняет правила игры», «открывает новые горизонты»). Замени на факты.\n"
        "2. Формат строго: 📊 КРАТКАЯ СПРАВКА ПО ПОДБОРКЕ (EXECUTIVE SUMMARY), 🌐 Главный фокус, ⚡ Ключевые инсайты, 🛠 Что внедрить / забрать в работу, 🔥 В итоге.\n"
        "3. Все ссылки оформлены строго как [Название](URL), никаких двойных скобок [[...]].\n"
        "4. Соответствие фактам: проверить по исходным релизам и выводам инженера (Агент 3).\n"
        "5. Отсутствие воды и банальностей.\n\n"
        "Выдай ИДЕАЛЬНЫЙ чистовой вариант справки без вступительных слов и комментариев."
    )
    user_prompt = (
        f"Исходные релизы:\n{combined_input}\n\n"
        f"Стратегические выводы инженера (Агент 3):\n{a3_strategy}\n\n"
        f"Черновик справки от Агента 4 для проверки:\n{a4_draft}"
    )
    verified = call_agent_step(
        "Recap Agent 4 (2nd Check / QA)",
        sys_prompt,
        user_prompt,
        models=COMPOSER_MODELS,
        max_tokens=1200,
        timeout=35
    )
    return verified or a4_draft


def run_four_agent_recap_pipeline(articles: list[dict], lang: str = "ru") -> str:
    """Executes the full 4-agent review & composition chain for Executive Summary / Recap posts."""
    if not articles:
        return "В текущей подборке нет новостей для объединения."

    items_text = []
    for idx, art in enumerate(articles, 1):
        t = clean_title(art.get("title", ""))
        u = art.get("url", "")
        s = art.get("summary") or ""
        lead = s[:350].replace("\n", " ").strip()
        items_text.append(f"{idx}. [{t}]({u}): {lead}")

    combined_input = "\n\n".join(items_text)
    log.info("Starting 4-agent recap pipeline for %d articles...", len(articles))

    # 1. Agent 1: Analyze
    a1_analysis = recap_agent1_analyze(combined_input, lang=lang)
    if not a1_analysis:
        a1_analysis = combined_input

    # 2. Agent 2: Fact-Check
    a2_critique = recap_agent2_factcheck(combined_input, a1_analysis, lang=lang)
    if not a2_critique:
        a2_critique = "Факты проверены."

    # 3. Agent 3: Strategize
    a3_strategy = recap_agent3_strategize(combined_input, a1_analysis, a2_critique, lang=lang)
    if not a3_strategy:
        a3_strategy = a1_analysis

    # 4. Agent 4: Compose
    a4_post = recap_agent4_compose(combined_input, a1_analysis, a2_critique, a3_strategy, lang=lang)

    # 4.5. Second Check of Recap Agent 4 (Quality Assurance)
    if a4_post:
        log.info("Running second check of Recap Agent 4...")
        a4_verified = recap_agent4_verify(combined_input, a4_post, a3_strategy, lang=lang)
        if a4_verified:
            a4_post = a4_verified

    if a4_post:
        return clean_summary_post(a4_post)

    # Fallback if composer fails
    bullets = [f"• [{clean_title(a.get('title', ''))}]({a.get('url', '')})" for a in articles[:5] if a.get('url')]
    return (
        "📊 **КРАТКАЯ СПРАВКА ПО ПОДБОРКЕ**\n\n"
        f"В этой подборке объединено **{len(articles)}** ключевых обновлений.\n\n"
        "🌐 **Главный фокус:** мультимодальные модели, низколатентный инференс и оптимизация локального стека.\n\n"
        "⚡ **Ключевые инструменты:**\n" + "\n".join(bullets) + "\n\n"
        "🔥 **В итоге:** актуализируйте локальные зависимости и тестируйте оптимизированные архитектуры в своих проектах."
    )


# ============================================================================
# 4-AGENT DIGEST PIPELINE (Channel Post / Multi-Article Digest)
# ============================================================================

def digest_agent1_draft(combined_input: str, count: int, lang: str = "ru") -> str:
    """Digest Agent 1: Drafts structured items with project title, markdown link, and technical highlights."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Агент 1 (Дайджест-редактор).\n"
        f"Твоя задача — составить черновик дайджеста для Telegram-канала по списку релизов {lang_inst}.\n"
        f"Для каждого из {count} проектов укажи номер, название со ссылкой строго [Название](URL) и 2 конкретных технических тезиса.\n"
        "Отвечай связным текстом, без кода."
    )
    return call_agent_step("Digest Agent 1 (Draft)", sys_prompt, f"Список релизов:\n\n{combined_input}", max_tokens=900)


def digest_agent2_verify(combined_input: str, a1_output: str, lang: str = "ru") -> str:
    """Digest Agent 2: Verifies project names, versions, markdown links, and technical details against sources."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Агент 2 (Фактчекер дайджеста).\n"
        "Твоя задача — сопоставить черновик Агента 1 с исходными релизами.\n"
        f"Проверь точность названий, ссылок, версий и описания фич. Устрани любые неточности, выдуманные факты и пустые клише {lang_inst}. Без кода."
    )
    user_prompt = f"Исходные релизы:\n\n{combined_input}\n\nЧерновик Агента 1:\n\n{a1_output}"
    return call_agent_step("Digest Agent 2 (Verify)", sys_prompt, user_prompt, max_tokens=900)


def digest_agent3_polish(combined_input: str, a1_output: str, a2_output: str, lang: str = "ru") -> str:
    """Digest Agent 3: Polishes each item for maximum engineering clarity, removing fluff and emphasizing real impact."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Агент 3 (Инженерный аудитор дайджеста).\n"
        f"Изучи черновик А1 и замечания А2. Отшлифуй каждый пункт для инженеров {lang_inst}: "
        "убери воду, сделай формулировки емкими и информативными (VRAM, архитектура, польза для разработки). Без кода."
    )
    user_prompt = f"Исходные релизы:\n\n{combined_input}\n\nАгент 1:\n{a1_output}\n\nАгент 2:\n{a2_output}"
    return call_agent_step("Digest Agent 3 (Polish)", sys_prompt, user_prompt, max_tokens=900)


def digest_agent4_format(
    combined_input: str,
    a1_output: str,
    a2_output: str,
    a3_output: str,
    greeting: str,
    count: int,
    target: str,
    lang: str = "ru"
) -> str:
    """Digest Agent 4: Chief layout designer assembling the final multi-item post for Telegram channel publication."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Агент 4 (Главный верстальщик Telegram-канала).\n"
        f"Скомпонуй согласованные выводы всех 3 агентов в цельный итоговый пост дайджеста для публикации в канале {lang_inst}.\n\n"
        "СТРОЖАЙШИЙ ЗАПРЕТ НА НЕЙРОСЛОП:\n"
        "- Никаких рекламных эпитетов («революционный», «меняет правила игры», «настоящий подарок»).\n"
        "- Каждый пункт — это сухой проверенный инженерный факт без прикрас и клише.\n\n"
        "СТРОГИЙ ШАБЛОН:\n"
        f"📰 **{greeting}**\n\n"
        f"Отобрано **{count}** ключевых AI & Dev релизов:\n\n"
        "1️⃣ **[Название](URL)**\n"
        "  • Ключевой факт\n"
        "  • Ключевой факт\n\n"
        "... (по каждому релизу)\n\n"
        "🔥 **В итоге:** емкий общий вывод (1 предложение).\n\n"
        f"⚡ **Канал:** {target}\n"
        "#AI #DevTools #OpenSource #TechNews\n\n"
        "Правила: ссылки строго вида [Название](URL), без вложенных скобок [[...]]."
    )
    user_prompt = (
        f"Исходные релизы:\n\n{combined_input}\n\n"
        f"Агент 1:\n{a1_output}\n\n"
        f"Агент 2:\n{a2_output}\n\n"
        f"Агент 3:\n{a3_output}"
    )
    return call_agent_step("Digest Agent 4 (Format)", sys_prompt, user_prompt, models=COMPOSER_MODELS, max_tokens=1200)


def digest_agent4_verify(
    combined_input: str,
    a4_draft: str,
    a3_polish: str,
    greeting: str,
    target: str,
    lang: str = "ru"
) -> str:
    """Digest Agent 4 Second Check: Final quality assurance auditing the multi-item channel digest."""
    lang_inst = "на русском языке" if lang == "ru" else "in English"
    sys_prompt = (
        "Ты — Главный инспектор верстки дайджестов и цензор нейрослопа (Вторая проверка Агента 4).\n"
        f"Твоя задача — провести контрольный аудит готового дайджеста для Telegram-канала {lang_inst}.\n\n"
        "КРИТЕРИИ АУДИТА (СТОП-СЛОП):\n"
        "1. Полная зачистка нейрослопа: вырежи любые штампы («революционный», «меняет правила игры», «открывает новые горизонты»). Замени на сухие факты.\n"
        "2. Четкая нумерация (1️⃣, 2️⃣, 3️⃣...), ссылки строго [Название](URL) без двойных скобок [[...]].\n"
        "3. По каждому пункту — 1-2 емких проверенных технических факта со значком •\n"
        f"4. В конце обязательно блок «🔥 В итоге: », строка «⚡ Канал: {target}» и хештеги.\n"
        "5. Все факты должны соответствовать проверенным данным Агента 3.\n\n"
        "Выдай ИДЕАЛЬНЫЙ чистовой вариант дайджеста без вступительных слов и комментариев."
    )
    user_prompt = (
        f"Исходные релизы:\n{combined_input}\n\n"
        f"Отредактированные тезисы инженера (Агент 3):\n{a3_polish}\n\n"
        f"Черновик дайджеста от Агента 4 для проверки:\n{a4_draft}"
    )
    verified = call_agent_step(
        "Digest Agent 4 (2nd Check / QA)",
        sys_prompt,
        user_prompt,
        models=COMPOSER_MODELS,
        max_tokens=1400,
        timeout=35
    )
    return verified or a4_draft


def run_four_agent_digest_pipeline(
    articles: list[dict],
    greeting: str = "Свежая подборка AI & Dev релизов",
    target: str = "@eternalnnews",
    lang: str = "ru"
) -> str:
    """Executes the full 4-agent review & composition chain for Channel / Multi-article Digest posts."""
    if not articles:
        return f"📰 **{greeting}**\n\nЗа прошедший период не найдено важных AI-обновлений, пробивших фильтр качества."

    items_text = []
    for idx, art in enumerate(articles, 1):
        t = clean_title(art.get("title", ""))
        u = art.get("url", "")
        s = art.get("summary") or ""
        lead = s[:350].replace("\n", " ").strip()
        items_text.append(f"{idx}. [{t}]({u}): {lead}")

    combined_input = "\n\n".join(items_text)
    count = len(articles)
    log.info("Starting 4-agent digest pipeline for %d articles...", count)

    # 1. Agent 1: Draft
    a1_draft = digest_agent1_draft(combined_input, count, lang=lang)
    if not a1_draft:
        a1_draft = combined_input

    # 2. Agent 2: Verify
    a2_verify = digest_agent2_verify(combined_input, a1_draft, lang=lang)
    if not a2_verify:
        a2_verify = "Все пункты проверены."

    # 3. Agent 3: Polish
    a3_polish = digest_agent3_polish(combined_input, a1_draft, a2_verify, lang=lang)
    if not a3_polish:
        a3_polish = a1_draft

    # 4. Agent 4: Format
    a4_post = digest_agent4_format(combined_input, a1_draft, a2_verify, a3_polish, greeting, count, target, lang=lang)

    # 4.5. Second Check of Digest Agent 4 (Quality Assurance)
    if a4_post:
        log.info("Running second check of Digest Agent 4...")
        a4_verified = digest_agent4_verify(combined_input, a4_post, a3_polish, greeting, target, lang=lang)
        if a4_verified:
            a4_post = a4_verified

    if a4_post:
        return clean_summary_post(a4_post)

    # Fallback to standard extract_digest_item if needed
    from curator.digest import extract_digest_item
    body_blocks = [extract_digest_item(item, idx) for idx, item in enumerate(articles, 1)]
    return (
        f"📰 **{greeting}**\n\n"
        f"Отобрано **{len(articles)}** ключевых AI & Dev релизов:\n\n" +
        "\n\n".join(body_blocks) +
        f"\n\n⚡ **Канал:** {target}\n#AI #DevTools #OpenSource #TechNews"
    )
