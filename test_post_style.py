import urllib.request, json, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def generate_post(title, url, content):
    sys_prompt = (
        "Ты — топовый автор Telegram-канала о нейросетях, открытых AI-моделях и технологиях для разработчиков.\n"
        "Твоя задача — написать глубокий, фактологический и красивый русскоязычный пост по новости в точности по формату.\n\n"
        "ФОРМАТ ПОСТА:\n"
        "1. Заголовок: подходящий эмодзи + КРАТКИЙ ЗАГОЛОВОК КАПСОМ (например: 🎬 KANDINSKY 5.0 — ЦЕЛОЕ СЕМЕЙСТВО ОТКРЫТЫХ AI-МОДЕЛЕЙ)\n\n"
        "2. Вводный абзац (лид): Название со ссылкой в markdown [Название](URL) — суть релиза и разработчик (1-2 предложения).\n\n"
        "3. Пункты с техническими деталями (от 3 до 6 пунктов, каждый начинается строго с зеленого кружка 🟢 и отделен пустой строкой):\n"
        "🟢 <Фича / Модель / Параметры> — параметры (B), VRAM требования, возможности, что делает, квантование, ComfyUI/Ollama/Docker, скорость, оптимизации.\n\n"
        "4. Итоговый вывод: начинается с «🔥 В итоге: » — четкое резюме практической ценности для инженера/пользователя.\n\n"
        "5. Хештеги в самом конце через пробел: 4-6 релевантных тегов (например: #AI #Нейросети #OpenSource #LLM ...)\n\n"
        "СТРОГО ЗАПРЕЩЕНО: писать «Что это:», «Почему это важно:», «Ключевые особенности:», использовать звездочки вместо 🟢. Пиши живым языком профильного Telegram-канала!"
    )
    body = {
        "model": "cf/@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Title: {title}\nURL: {url}\nContent excerpt:\n{content}"}
        ],
        "max_tokens": 700,
        "temperature": 0.25
    }
    gateway_token = os.getenv("GATEWAY_TOKEN", "")
    req = urllib.request.Request(
        "http://localhost:20128/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {gateway_token}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", errors="replace")
        if "data: [DONE]" in raw:
            raw = raw.split("data: [DONE]")[0].strip()
        data = json.loads(raw)
        return data["choices"][0]["message"]["content"]

post = generate_post(
    "Kandinsky 5.0 release: open source family of diffusion models for video and images",
    "https://github.com/kandinskylab/kandinsky-5",
    "Kandinsky 5.0 is an open-source family of diffusion models from Kandinsky Lab for text-to-video, image-to-video, and image generation. Video Pro has 19B params, Video Lite has 2B params requiring 12GB VRAM. Image Lite has 6B params with Russian text and concept rendering. Image Editing 6B can replace objects. Supports ComfyUI, Hugging Face Diffusers, MagCache, and offloading."
)
print("--- GENERATED POST ---")
print(post)
