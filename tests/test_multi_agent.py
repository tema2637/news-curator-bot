import unittest
from unittest.mock import patch
from curator.multi_agent import (
    agent1_research,
    agent2_factcheck,
    agent3_refine,
    agent4_compose,
    run_four_agent_pipeline,
    run_four_agent_recap_pipeline,
    run_four_agent_digest_pipeline
)


class TestMultiAgentPipeline(unittest.TestCase):
    def test_pipeline_sequential_flow(self):
        call_history = []

        def mock_call_step(role_name, sys_prompt, user_prompt, **kwargs):
            call_history.append((role_name, user_prompt))
            if "Agent 1" in role_name:
                return "FACTS: llama.cpp b11792 keeps d2t tensor on GPU via set_rows."
            elif "Agent 2" in role_name:
                return "CRITIQUE: Facts verified against PR #30912. No CUDA limitation found."
            elif "Agent 3" in role_name:
                return "ENHANCED: Speeds up speculative decoding and MTP by avoiding PCIe roundtrips."
            elif "Agent 4" in role_name:
                return (
                    "⚡️ [llama.cpp b11792](https://github.com/ggml-org/llama.cpp/releases/tag/b11792): d2t-тензор в VRAM\n\n"
                    "Выкатили оптимизацию спекулятивного декодирования.\n\n"
                    "• На пальцах: ускорили работу нейросети на видеокарте.\n"
                    "• Под капотом: d2t-тензор удерживается в VRAM\n"
                    "• Фича: ускорение спекулятивного сэмплинга на GPU\n"
                    "• Подвох: для CPU эффекта нет\n\n"
                    "🔥 Итог: обновление рекомендовано всем пользователям draft-моделей.\n\n"
                    "#AI #llama_cpp #OpenSource"
                )
            return ""

        with patch("curator.multi_agent.call_agent_step", side_effect=mock_call_step):
            res = run_four_agent_pipeline(
                title="llama.cpp b11792",
                url="https://github.com/ggml-org/llama.cpp/releases/tag/b11792",
                content="PR #30912: llama : place d2t by its set_rows use so it can stay on the GPU",
                lang="ru"
            )

            # Ensure all steps including Agent 4's second check were invoked in strict order
            self.assertEqual(len(call_history), 5)
            self.assertIn("Agent 1", call_history[0][0])
            self.assertIn("Agent 2", call_history[1][0])
            self.assertIn("Agent 3", call_history[2][0])
            self.assertIn("Agent 4 (Lead Editor)", call_history[3][0])
            self.assertIn("Agent 4 (2nd Check / QA)", call_history[4][0])

            # Verify Agent 2 received Agent 1's facts
            self.assertIn("FACTS: llama.cpp b11792", call_history[1][1])

            # Verify Agent 3 received Agent 1's facts and Agent 2's critique
            self.assertIn("FACTS: llama.cpp b11792", call_history[2][1])
            self.assertIn("CRITIQUE: Facts verified", call_history[2][1])

            # Verify Agent 4 received all 3 agents' findings
            self.assertIn("FACTS: llama.cpp b11792", call_history[3][1])
            self.assertIn("CRITIQUE: Facts verified", call_history[3][1])
            self.assertIn("ENHANCED: Speeds up", call_history[3][1])

            # Verify Agent 4 Second Check received Agent 4's draft and Agent 3's facts
            self.assertIn("ENHANCED: Speeds up", call_history[4][1])
            self.assertIn("llama.cpp b11792", call_history[4][1])

            # Verify final post is properly formatted in Backdoor style
            self.assertIn("llama.cpp b11792", res)
            self.assertIn("• Под капотом:", res)
            self.assertIn("🔥 Итог:", res)

    def test_pipeline_graceful_fallback_when_agents_fail(self):
        # Even if Agent 1 and Agent 2 return empty strings, pipeline shouldn't crash
        def mock_failing_step(role_name, sys_prompt, user_prompt, **kwargs):
            if "Agent 4" in role_name:
                return (
                    "🚀 **NEW TOOL**\n\n[New Tool](https://example.com) — лид.\n\n"
                    "🟢 Фича 1\n\n🔥 В итоге: обновляйтесь.\n\n#AI"
                )
            return ""

        with patch("curator.multi_agent.call_agent_step", side_effect=mock_failing_step):
            res = run_four_agent_pipeline(
                title="New Tool",
                url="https://example.com",
                content="Initial release data",
                lang="ru"
            )
            self.assertIn("NEW TOOL", res)
            self.assertIn("🟢 Фича 1", res)

    def test_recap_pipeline_flow(self):
        call_history = []

        def mock_call_step(role_name, sys_prompt, user_prompt, **kwargs):
            call_history.append(role_name)
            if "Recap Agent 4" in role_name:
                return (
                    "📊 **КРАТКАЯ СПРАВКА ПО ПОДБОРКЕ (EXECUTIVE SUMMARY)**\n\n"
                    "🌐 **Главный фокус:** Оптимизация инференса.\n\n"
                    "⚡ **Ключевые инсайты:**\n• [Tool](https://tool.com) — суть.\n\n"
                    "🛠 **Что внедрить:** Тестировать локально.\n\n"
                    "🔥 **В итоге:** Всё готово."
                )
            return f"Step from {role_name}"

        with patch("curator.multi_agent.call_agent_step", side_effect=mock_call_step):
            articles = [
                {"title": "Tool A", "url": "https://a.com", "summary": "Summary A"},
                {"title": "Tool B", "url": "https://b.com", "summary": "Summary B"}
            ]
            res = run_four_agent_recap_pipeline(articles, lang="ru")
            self.assertEqual(len(call_history), 5)
            self.assertIn("Recap Agent 1", call_history[0])
            self.assertIn("Recap Agent 2", call_history[1])
            self.assertIn("Recap Agent 3", call_history[2])
            self.assertIn("Recap Agent 4 (Lead Editor)", call_history[3])
            self.assertIn("Recap Agent 4 (2nd Check / QA)", call_history[4])
            self.assertIn("КРАТКАЯ СПРАВКА ПО ПОДБОРКЕ", res)
            self.assertIn("[Tool](https://tool.com)", res)

    def test_digest_pipeline_flow(self):
        call_history = []

        def mock_call_step(role_name, sys_prompt, user_prompt, **kwargs):
            call_history.append(role_name)
            if "Digest Agent 4" in role_name:
                return (
                    "📰 **Свежая подборка AI & Dev релизов**\n\n"
                    "Отобрано **2** ключевых AI & Dev релиза:\n\n"
                    "1️⃣ **[Tool A](https://a.com)**\n  • Фича 1\n\n"
                    "2️⃣ **[Tool B](https://b.com)**\n  • Фича 2\n\n"
                    "🔥 **В итоге:** Отличная подборка.\n\n"
                    "⚡ **Канал:** @eternalnnews\n#AI #Tech"
                )
            return f"Step from {role_name}"

        with patch("curator.multi_agent.call_agent_step", side_effect=mock_call_step):
            articles = [
                {"title": "Tool A", "url": "https://a.com", "summary": "Summary A"},
                {"title": "Tool B", "url": "https://b.com", "summary": "Summary B"}
            ]
            res = run_four_agent_digest_pipeline(articles, greeting="Свежая подборка", target="@eternalnnews", lang="ru")
            self.assertEqual(len(call_history), 5)
            self.assertIn("Digest Agent 1", call_history[0])
            self.assertIn("Digest Agent 2", call_history[1])
            self.assertIn("Digest Agent 3", call_history[2])
            self.assertIn("Digest Agent 4 (Format)", call_history[3])
            self.assertIn("Digest Agent 4 (2nd Check / QA)", call_history[4])
            self.assertIn("Свежая подборка", res)
            self.assertIn("1️⃣ **[Tool A](https://a.com)**", res)

    def test_is_hollow_post_detection(self):
        from curator.multi_agent import is_hollow_post
        # Empty markers should be hollow
        self.assertTrue(is_hollow_post("⚡️ [Tool](url): release\n\n• Под капотом:\n\n🔥 Итог: ok"))
        self.assertTrue(is_hollow_post('{"skip": true, "reason": "empty"}'))
        self.assertTrue(is_hollow_post(""))
        self.assertTrue(is_hollow_post("Too short"))

        # Real post with substance should pass
        real_post = (
            "⚡️ [llama.cpp b11792](https://github.com/ggml-org/llama.cpp): d2t in VRAM\n\n"
            "Выкатили оптимизацию спекулятивного декодирования для ускорения генерации на GPU.\n\n"
            "• Под капотом: d2t-тензор удерживается в VRAM без лишних копирований по шине PCIe.\n"
            "• Фича: ускорение спекулятивного сэмплинга на 15-20% при использовании драфт-моделей.\n\n"
            "🔥 Итог: обновление рекомендовано всем пользователям CUDA.\n\n"
            "#AI #DevTools"
        )
        self.assertFalse(is_hollow_post(real_post))

if __name__ == "__main__":
    unittest.main()
