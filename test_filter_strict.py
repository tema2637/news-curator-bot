import urllib.request, json

def test(headline):
    sys_prompt = (
        "You are a strict technical filter for an AI & Software Engineering news channel.\n"
        "Output ONLY valid JSON:\n"
        '{"signal": 0.0-1.0, "fact": 0.0-1.0, "hype": 0.0-1.0, "category": "free_api" | "tools" | "models" | "other", "topics": ["topic1"]}\n'
        "CRITICAL RULES:\n"
        "- ONLY approve articles about Artificial Intelligence, Machine Learning, LLMs, Neural Networks, AI Media/Code Generation, Developer Tools, Open Source frameworks, and Free/cheap APIs.\n"
        "- If the article is about biology, medicine, politics, war, general news, or non-technical topics, signal MUST be 0.0 and category MUST be 'other'.\n"
        "- Be ruthlessly strict. If it is not directly useful to an AI/software engineer, signal: 0.0."
    )
    body = {
        "model": "cf/@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Headline: {headline}"}
        ],
        "max_tokens": 80,
        "temperature": 0.0
    }
    gateway_token = os.getenv("GATEWAY_TOKEN", "")
    req = urllib.request.Request(
        "http://localhost:20128/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {gateway_token}"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode("utf-8", errors="replace")
        if "data: [DONE]" in raw:
            raw = raw.split("data: [DONE]")[0].strip()
        data = json.loads(raw)
        print(f"[{headline}] -> {data['choices'][0]['message']['content']}")

test("The ovary doesn't retire after menopause")
test("Ukraine claims first drone evacuation of wounded soldier")
test("Kandinsky 5.0 family of open models released")
test("PyTorch 2.5 with RoPE kernel optimization")
