"""
curator/evaluator.py - System 1 Llama 70B classifier and scoring calculator.
"""
import os, json, re, logging, time, urllib.request

log = logging.getLogger("curator.evaluator")

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:20128/v1")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "")
CLASSIFIER_MODELS = ["mistral/mistral-small-latest", "oc/deepseek-v4.1-flash-free"]

VALID_CATEGORIES = {
    "models",
    "tools",
    "free_api",
    "local_ai",
    "agents",
    "audio",
    "vision",
    "hardware",
    "tech_news"
}

def parse_classification_json(raw: str) -> dict:
    fallback = {
        "signal": 0.0,
        "fact": 0.5,
        "hype": 0.5,
        "category": "other",
        "topics": []
    }
    if not raw or not isinstance(raw, str):
        return fallback

    text = raw.strip()
    if "data: [DONE]" in text:
        text = text.split("data: [DONE]")[0].strip()

    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            code_body = parts[1]
            if code_body.startswith("json"):
                code_body = code_body[4:]
            text = code_body.strip()

    idx = text.find("{")
    if idx == -1:
        return fallback

    try:
        data, _ = json.JSONDecoder().raw_decode(text, idx)
        if not isinstance(data, dict):
            return fallback
        cat = data.get("category", "other")
        if cat not in VALID_CATEGORIES:
            cat = "other"
        topics = data.get("topics", [])
        if not isinstance(topics, list):
            topics = []
        sig = float(data.get("signal", 0.0))
        fact = float(data.get("fact", 0.5))
        hype = float(data.get("hype", 0.5))
        if cat == "other":
            sig = 0.0
        elif sig < 0.25:
            sig = max(sig, fact * 0.85)
        return {
            "signal": sig,
            "fact": fact,
            "hype": hype,
            "category": cat,
            "topics": [str(t).lower() for t in topics]
        }
    except Exception as e:
        log.warning("parse_classification_json failed on '%s': %s", raw[:60], e)
        return fallback

AI_KEYWORDS = {
    # English
    "ai", "llm", "llms", "model", "models", "gpt", "claude", "deepseek", "qwen", "llama",
    "mistral", "gemini", "grok", "vllm", "ollama", "sglang", "comfyui", "flux", "diffusion",
    "tts", "stt", "whisper", "voice", "weights", "finetune", "gguf", "benchmark", "inference",
    "token", "tokens", "cuda", "pytorch", "agent", "agents", "rag", "eval", "lora", "prompt",
    "caching", "coder", "coding", "cursor", "copilot", "github", "reverse", "opensource",
    "gpu", "vram", "nvidia", "rtx", "amd", "intel", "apple", "openai", "anthropic", "google",
    "hardware", "chip", "chips", "server", "linux", "docker", "python", "security", "fuzzer",
    "router", "api", "framework", "robot", "robotics", "automation",
    # Russian
    "ии", "нейросеть", "нейросети", "нейросетей", "нейросетью", "нейронка", "нейронки",
    "нейронок", "модель", "модели", "моделей", "дипсик", "клауд", "гпт", "чатгпт", "агент",
    "агенты", "агентов", "токен", "токены", "токенов", "промпт", "промптинг", "бенчмарк",
    "бенчмарки", "вайбкодинг", "вайб-кодинг", "кодинг", "чек-лист", "реверс", "опенсорс",
    "скилл", "генерация", "распознавание", "датасет", "квантование", "чип", "чипы", "процессор",
    "видеокарта", "софт", "разработка", "уязвимость", "безопасность", "роутер", "озвучка",
    "железо", "память", "автоматизация", "яндекс", "сбер", "хабр"
}

def classify_with_jev(title: str, content: str = "", gateway_url: str = GATEWAY_URL, token: str = GATEWAY_TOKEN) -> dict | None:
    """Fast System One / Jev decision evaluation via 9Router /v1/systemone."""
    body = {
        "model": "opencode/jev-1.13-free",
        "state": f"Headline: {title}\nDetails: {content[:1000]}",
        "questions": {
            "signal": {
                "type": "noul",
                "instructions": "Is this high-signal technical news about AI/ML models, developer tools, or open-source software engineering?",
                "criteria": {
                    "true": "Technical release, model weights, framework, developer tool, practical benchmark, or free API for developers.",
                    "false": "General non-technical news, consumer gossip, marketing hype without substance, or noise."
                }
            },
            "category": {
                "type": "choice",
                "instructions": "Select the primary technical category.",
                "criteria": {
                    "tools": "Developer tools, libraries, local runtimes, CLI tools, compilers",
                    "models": "Open weights, neural network architectures, checkpoints, benchmarks",
                    "free_api": "Free API access, token routing, proxies, quotas",
                    "other": "Irrelevant or low-technical noise"
                }
            }
        }
    }
    try:
        req = urllib.request.Request(
            f"{gateway_url}/systemone",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            answers = data.get("answers", {})
            sig_ans = answers.get("signal", {})
            cat_ans = answers.get("category", {})
            prob_true = float(sig_ans.get("probabilityTrue", 0.0))
            chosen_cat = cat_ans.get("choice", "other")
            if chosen_cat not in VALID_CATEGORIES:
                chosen_cat = "other"
            log.info("[Jev SystemOne] Evaluated '%s': signal=%.2f, category=%s", title[:40], prob_true, chosen_cat)
            return {
                "signal": prob_true if chosen_cat != "other" else 0.0,
                "fact": 0.9,
                "hype": 0.1,
                "category": chosen_cat,
                "topics": ["jev", chosen_cat]
            }
    except Exception as e:
        log.debug("[Jev SystemOne] Upstream unavailable (%s), falling back to DeepSeek classifier", e)
        return None

def classify_article(title: str, source: str = "", gateway_url: str = GATEWAY_URL, token: str = GATEWAY_TOKEN) -> dict:
    # 1. Fast-path: Hugging Face models are inherently high-signal AI models
    if source == "huggingface":
        return {
            "signal": 0.95,
            "fact": 1.0,
            "hype": 0.1,
            "category": "models",
            "topics": ["huggingface", "model"]
        }

    # 2. Fast-path: GitHub releases from our curated AI tools list
    if source == "github":
        return {
            "signal": 0.95,
            "fact": 1.0,
            "hype": 0.05,
            "category": "tools",
            "topics": ["github", "tools", "release"]
        }

    # 3. Rule-based pre-filter: reject obviously non-AI/non-tech headlines without LLM call
    t_lower_tokens = set(re.findall(r"[a-zA-Zа-яА-Я0-9]+", title.lower()))
    t_lower_str = title.lower()
    has_match = any(k in t_lower_tokens for k in AI_KEYWORDS) or any(
        k in t_lower_str for k in [
            "deepseek", "llama", "qwen", "comfyui", "vllm", "нейро", "ии-", "gpt", "claude",
            "openai", "nvidia", "rtx", "apple", "агент", "робот", "озвучк", "диффуз", "промпт",
            "чип", "vram", "fuzzer", "уязвимост", "безопасност", "gguf", "omni", "elevenlabs"
        ]
    )
    if not has_match:
        return {
            "signal": 0.0,
            "fact": 0.5,
            "hype": 0.5,
            "category": "other",
            "topics": []
        }

    # 4. Try Jev (System One) decision evaluation first
    jev_decision = classify_with_jev(title, gateway_url=gateway_url, token=token)
    if jev_decision is not None:
        return jev_decision

    sys_prompt = (
        "You are a technical curator filter for an AI, Open-Source, Developer Tools & Technology channel.\n"
        "Output ONLY valid JSON:\n"
        '{"signal": 0.0-1.0, "fact": 0.0-1.0, "hype": 0.0-1.0, "category": "models" | "tools" | "agents" | "local_ai" | "audio" | "vision" | "free_api" | "hardware" | "tech_news" | "other", "topics": ["topic1"]}\n'
        "CRITICAL RULES:\n"
        "- APPROVE (signal 0.7-1.0): AI/ML models (open weights or proprietary like GPT/Claude/DeepSeek/Qwen), AI agents, coding tools, developer libraries, local AI (llama.cpp/Ollama/vLLM), hardware (GPUs, Nvidia, chips, accelerators), voice/audio AI, image/video generation, cybersecurity/vulnerabilities, and practical software engineering.\n"
        "- REJECT (category 'other', signal 0.0): politics, celebrity gossip, war, non-tech general news, lifestyle, sports, crypto scams, or spam.\n"
        "- If it is real tech or AI news for developers or power users, choose the best category and assign signal >= 0.75."
    )
    body = {
        "model": CLASSIFIER_MODELS[0],
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Headline: {title}"}
        ],
        "max_tokens": 300,
        "temperature": 0.0,
        "stream": False
    }
    for model_name in CLASSIFIER_MODELS:
        body["model"] = model_name
        req = urllib.request.Request(
            f"{gateway_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        )
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    if "data: [DONE]" in raw:
                        raw = raw.split("data: [DONE]")[0].strip()
                    if raw.startswith("data: "):
                        lines = [l[6:].strip() for l in raw.split("\n") if l.startswith("data: ") and l[6:].strip() != "[DONE]"]
                        if lines:
                            raw = lines[-1]
                    res_data = json.loads(raw)
                    raw_c = res_data["choices"][0]["message"].get("content")
                    if isinstance(raw_c, list):
                        content = "\n".join(b.get("text", "") for b in raw_c if isinstance(b, dict) and b.get("type") == "text").strip()
                    else:
                        content = str(raw_c or "").strip()
                    parsed = parse_classification_json(content)
                    if parsed.get("category") != "other" or parsed.get("signal", 0) > 0:
                        return parsed
                    return parsed
            except Exception as e:
                if "429" in str(e):
                    log.warning("classify_article 429 on %s for '%s', switching model...", model_name, title[:30])
                    break
                time.sleep(1.0)

    return parse_classification_json("")

TOPIC_KEYWORDS_MAP = {
    "models": {"model", "models", "weights", "checkpoint", "deepseek", "llama", "qwen", "mistral", "gemini", "grok", "модель", "модели", "веса", "gpt", "claude"},
    "tools": {"tools", "tool", "library", "framework", "compiler", "cli", "vllm", "sglang", "comfyui", "инструмент", "библиотека", "движок", "github", "gitlab"},
    "free_api": {"api", "free_api", "proxy", "token", "quota", "routing", "прокси", "токен", "апи"},
    "local_ai": {"local_ai", "gguf", "ollama", "llama.cpp", "quantization", "локальный", "квантование"},
    "agents": {"agent", "agents", "rag", "reflection", "autonomous", "агент", "агенты", "cursor", "copilot", "fuzzer", "фаззер"},
    "audio": {"audio", "whisper", "voice", "tts", "stt", "transcription", "голос", "распознавание", "озвучка", "звук"},
    "vision": {"vision", "diffusion", "flux", "image", "video", "генерация", "видео", "изображения", "midjourney", "sora"},
    "hardware": {"gpu", "vram", "nvidia", "rtx", "chip", "чип", "процессор", "видеокарта", "intel", "amd", "apple", "arm", "h100", "5090", "tsmc"},
    "tech_news": {"tech", "it", "софт", "разработка", "уязвимость", "безопасность", "security", "linux", "docker", "python"},
}

def calculate_score(
    title: str,
    metrics: dict,
    weights: dict[str, float],
    active_topics: set[str] | None = None,
    blacklist: set[str] | None = None
) -> tuple[float, list[str]]:
    t_lower = title.lower()

    # 1. Blacklist check: reject immediately if title contains any blacklisted term
    if blacklist:
        for b in blacklist:
            clean_b = b.strip().lower()
            if clean_b and clean_b in t_lower:
                return 0.0, [f"blacklist:{clean_b}"]

    cat = metrics.get("category")
    if cat not in VALID_CATEGORIES or metrics.get("signal", 0.0) < 0.25:
        return 0.0, []

    # 2. Active categories filter: if category is not enabled in active_topics
    if active_topics is not None and len(active_topics) > 0 and cat not in active_topics:
        # Check if title or extracted topics match any enabled category's keywords
        has_subtopic = False
        for top in active_topics:
            kws = TOPIC_KEYWORDS_MAP.get(top, {top})
            if any(k in t_lower for k in kws) or any(k in metrics.get("topics", []) for k in kws):
                has_subtopic = True
                break
        if not has_subtopic:
            return 0.0, []

    base = (metrics["signal"] * 0.6) + (metrics["fact"] * 0.4) - (metrics["hype"] * 0.3)
    mult = 1.0
    matched_topics = []
    for topic, weight in weights.items():
        if topic in t_lower or topic in metrics.get("topics", []):
            mult *= weight
            matched_topics.append(topic)
    return round(max(0.0, base * mult), 2), matched_topics
