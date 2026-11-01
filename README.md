# News Curator & Digest Bot

Autonomous AI-powered technical news curator and scheduled digest bot for Telegram.

## Why This Architecture?
- **Zero Heavy AI SDKs**: No LangChain, LlamaIndex, or proprietary OpenAI libraries. Communication with LLMs is built entirely on Python stdlib (`urllib.request`, `asyncio`, `sqlite3`, `xml.etree`).
- **Universal LLM Compatibility**: Works out-of-the-box with any OpenAI-compatible API gateway (Ollama, vLLM, OpenRouter, LiteLLM, 9Router).
- **Two-Tier AI Processing**:
  - **System 1 (High-speed Triage)**: Fast JSON classification and signal scoring to drop noise before invoking heavy models.
  - **System 2 (Multi-Agent Editorial Pipeline)**: Sequential chain of specialized steps (Researcher -> Fact-Checker -> Refiner -> Editor) to produce concise, high-signal posts.
- **Continuous Taste Flywheel**: Interactive Telegram inline vote buttons (`👍` / `👎`) dynamically adjust category and topic weights in SQLite WAL storage.

## Ingestion Sources
- **GitHub**: RSS/Atom release feeds for top open-source projects (llama.cpp, vLLM, ComfyUI, etc.) without API rate limit exhaustion.
- **Hacker News**: Firebase Realtime API (`topstories` & `showstories`).
- **Reddit**: Clean public JSON feeds (`r/LocalLLaMA`, `r/MachineLearning`).
- **Telegram Channels**: Curated feeds via MTProto client.

## Quick Start

### 1. Requirements
Only Python 3.10+ and Telethon are needed:
```bash
pip install -r requirements.txt
```

### 2. Configuration
Copy the environment template and set your credentials:
```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `TG_BOT_TOKEN` | Telegram Bot token from @BotFather | Required |
| `TG_API_ID` | Telegram API ID from my.telegram.org | Required |
| `TG_API_HASH` | Telegram API Hash | Required |
| `TG_CHAT_ID` | Target Telegram Chat / Channel ID | Required |
| `GATEWAY_URL` | OpenAI-compatible base URL | `http://127.0.0.1:20128/v1` |
| `GATEWAY_TOKEN` | Bearer token for LLM API | Optional |
| `PROXY_HOST` | MTProto proxy host | Optional |
| `PROXY_PORT` | MTProto proxy port | Optional |
| `PROXY_SECRET` | MTProto proxy secret | Optional |

### 3. Run Daemon
```bash
python news_daemon.py
```

### 4. Running Tests
Unit tests require zero network access or API tokens:
```bash
python -m unittest discover tests
```

## Example Post Output

```text
🔥 llama.cpp b11792: оптимизация flash-attention для CUDA
Категория: #tools #local_ai | Скорость: +18%

🟢 Под капотом:
• Переписан CUDA-кернел FlashAttention-2 с поддержкой нестандартных размерностей квантования (Q4_K_M, Q8_0).
• Исправлен регресс потребления VRAM при длинных контекстах (>32k токенов) на RTX 40-й серии.

💡 Почему это важно: локальный инференс 70B моделей на потребительских GPU становится ощутимо быстрее без потери точности.

🔗 Репозиторий: github.com/ggerganov/llama.cpp/releases/tag/b11792
```

## License
MIT License. See [LICENSE](LICENSE) for details.
