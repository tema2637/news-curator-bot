import unittest
from curator.dedup import (
    significant_tokens, jaccard, extract_pr_number, extract_repo,
    find_duplicate, merge_sources, format_discussion_line, build_source_entry,
)


class TestDedup(unittest.TestCase):
    def test_significant_tokens_drops_noise(self):
        toks = significant_tokens("llama.cpp b11792: ggml-cuda optimize flash attention")
        # dots/hyphens split so "llama.cpp" matches "llama cpp"
        self.assertIn("llama", toks)
        self.assertIn("cpp", toks)
        self.assertIn("optimize", toks)
        self.assertNotIn("b11792", toks)  # build number ignored
        self.assertNotIn("the", toks)

    def test_version_and_stopword_filtering(self):
        toks = significant_tokens("ComfyUI v0.3.10 new release update")
        self.assertIn("comfyui", toks)
        self.assertNotIn("v0", toks)
        self.assertNotIn("release", toks)
        self.assertNotIn("new", toks)

    def test_jaccard_bounds(self):
        self.assertEqual(jaccard({"a", "b"}, {"a", "b"}), 1.0)
        self.assertEqual(jaccard({"a"}, {"b"}), 0.0)
        self.assertEqual(jaccard(set(), {"b"}), 0.0)

    def test_extract_pr_and_repo(self):
        self.assertEqual(extract_pr_number("llama : place d2t (#30912)"), "30912")
        self.assertEqual(extract_pr_number("no pr here"), "")
        self.assertEqual(
            extract_repo("https://github.com/GGML-org/llama.cpp/releases/tag/b1"),
            "ggml-org/llama.cpp".lower()
        )

    def test_same_url_is_duplicate(self):
        heads = [{"id": "a", "title": "Something", "url": "https://x.com/1", "cluster_id": "a"}]
        dup = find_duplicate(heads, "Different headline", "https://x.com/1")
        self.assertEqual(dup["id"], "a")

    def test_same_pr_number_is_duplicate(self):
        heads = [{
            "id": "a",
            "title": "llama : place d2t so it can stay on the GPU (#30912)",
            "url": "https://github.com/ggml-org/llama.cpp/releases/tag/b11792",
            "cluster_id": "a",
        }]
        dup = find_duplicate(heads, "llama.cpp b11792 (#30912)", "https://reddit.com/r/LocalLLaMA/x")
        self.assertEqual(dup["id"], "a")

    def test_similar_title_is_duplicate(self):
        heads = [{
            "id": "a",
            "title": "Google open sources Harness2 for self-improving agents",
            "url": "https://reddit.com/1",
            "cluster_id": "a",
        }]
        dup = find_duplicate(heads, "Google open-sources Harness2 self-improving agent",
                            "https://news.ycombinator.com/item?id=2", threshold=0.5)
        self.assertIsNotNone(dup)

    def test_unrelated_titles_not_duplicates(self):
        heads = [{
            "id": "a",
            "title": "ComfyUI adds Flux ControlNet nodes",
            "url": "https://reddit.com/1",
            "cluster_id": "a",
        }]
        dup = find_duplicate(heads, "vLLM raises throughput with PagedAttention v3",
                            "https://github.com/vllm-project/vllm/releases/tag/v9")
        self.assertIsNone(dup)

    def test_merge_sources_dedupes_same_entry(self):
        e = build_source_entry("t", "https://x.com/1", "reddit")
        raw = merge_sources("[]", e)
        raw2 = merge_sources(raw, e)
        self.assertEqual(raw, raw2)

    def test_format_discussion_line(self):
        raw = merge_sources("[]", build_source_entry("t", "https://r.com/1", "reddit"))
        raw = merge_sources(raw, build_source_entry("t", "https://n.com/1", "hn"))
        line = format_discussion_line(raw)
        self.assertIn("Обсуждают", line)
        self.assertIn("[Reddit](https://r.com/1)", line)
        self.assertIn("[HN](https://n.com/1)", line)
        self.assertEqual(format_discussion_line("[]"), "")
        self.assertEqual(format_discussion_line(""), "")


if __name__ == "__main__":
    unittest.main()
