"""
雙層分類（tags 主題標籤）單元測試
================================

執行方式：
    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import doc_model
import events as ev_mod
import tags


class TestTagDictionary(unittest.TestCase):
    def test_ids_are_snake_case_and_grouped(self):
        for tid, t in tags.TAGS.items():
            self.assertRegex(tid, r"^[a-z][a-z0-9_]*$")
            self.assertIn(t["group"], tags.TAG_GROUPS)
            self.assertTrue(t["label"] and t["desc"])

    def test_aliases_point_to_real_tags(self):
        for alias, tid in tags.TAG_ALIASES.items():
            self.assertIn(tid, tags.TAGS, alias)

    def test_prompt_spec_lists_every_tag(self):
        spec = tags.tag_spec_for_prompt()
        for tid in tags.TAG_IDS:
            self.assertIn(f"- {tid}（", spec)


class TestNormalizeAndMerge(unittest.TestCase):
    def test_normalize_filters_unknown_dedups_and_caps(self):
        raw = ["AI_Agent", "ai_agent", "not_a_tag", "coding-agent", "hbm", "ransomware"]
        self.assertEqual(tags.normalize_tags(raw), ["ai_agent", "coding_ai", "memory_hbm"])

    def test_normalize_accepts_string_and_bad_types(self):
        self.assertEqual(tags.normalize_tags("ai_agent、zero_day"), ["ai_agent", "zero_day"])
        self.assertEqual(tags.normalize_tags(None), [])
        self.assertEqual(tags.normalize_tags(42), [])
        self.assertEqual(tags.normalize_tags([]), [])

    def test_merge_ranks_by_frequency_then_first_seen(self):
        merged = tags.merge_tags(["ai_agent", "coding_ai"], ["ai_security", "ai_agent"],
                                 ["ai_security", "data_breach"])
        self.assertEqual(merged, ["ai_agent", "ai_security", "coding_ai"])

    def test_merge_handles_empty(self):
        self.assertEqual(tags.merge_tags([], []), [])


class TestRuleTags(unittest.TestCase):
    def test_title_hit_is_enough(self):
        self.assertIn("ransomware", tags.rule_tags("Synology NAS 遭勒索軟體攻擊"))

    def test_single_summary_mention_is_not_enough(self):
        out = tags.rule_tags("某公司發表年度報告", "內文順帶一提勒索。")
        self.assertNotIn("ransomware", out)

    def test_exclude_blocks_false_positive(self):
        self.assertNotIn("robotics", tags.rule_tags("銀行推出聊天機器人客服"))

    def test_cap_at_three(self):
        out = tags.rule_tags("NVIDIA GPU 與 HBM 記憶體、CoWoS 封裝、資料中心電力、液冷", min_score=1)
        self.assertLessEqual(len(out), tags.MAX_TAGS)


class TestPipelineIntegration(unittest.TestCase):
    def _src(self, url: str) -> dict:
        return {"url": url, "source_name": "TechCrunch", "source_kind": "media"}

    def test_normalize_event_keeps_valid_tags_only(self):
        ev = ev_mod._normalize_event({
            "title": "某 AI 代理遭提示注入", "summary": "摘要" * 30,
            "category": "cybersecurity", "importance": 7,
            "tags": ["ai_security", "AI Agent", "made_up"],
        }, {"url": "u1", "source_name": "x"})
        self.assertEqual(ev["tags"], ["ai_security", "ai_agent"])

    def test_programmatic_merge_unions_tags(self):
        a = {"title": "A", "summary": "s", "who": [], "importance": 5,
             "tags": ["ai_agent"], "sources": [self._src("u1")]}
        b = {"title": "B", "summary": "s", "who": [], "importance": 6,
             "tags": ["ai_security", "ai_agent"], "sources": [self._src("u2")]}
        ev_mod._merge_into_programmatic(a, b)
        self.assertEqual(a["tags"], ["ai_agent", "ai_security"])

    def test_llm_merge_helper_unions_tags(self):
        a = {"title": "A", "who": [], "importance": 5, "tags": ["coding_ai"],
             "sources": [self._src("u1")]}
        b = {"title": "B", "who": [], "importance": 5, "tags": ["open_source"],
             "sources": [self._src("u2")]}
        ev_mod._merge_into(a, b)
        self.assertEqual(a["tags"], ["coding_ai", "open_source"])

    def test_doc_marks_tag_origin(self):
        new = doc_model.event_to_doc({"event_id": "e1", "tags": ["robotics"]}, "2026-11-19", False)
        self.assertEqual((new["tags"], new["tags_by"], new["tags_version"]),
                         (["robotics"], "extract", tags.TAGS_VERSION))
        legacy = doc_model.event_to_doc({"event_id": "e2"}, "2026-06-01", False)
        self.assertEqual((legacy["tags"], legacy["tags_by"]), ([], "none"))

    def test_stats_count_tags(self):
        evs = [
            {"category": "cybersecurity", "importance": 8, "mention_count": 3,
             "tags": ["ai_security", "ai_agent"], "sources": []},
            {"category": "products_apps", "importance": 5, "mention_count": 1,
             "tags": ["ai_agent"], "sources": []},
        ]
        st = doc_model.tag_stats(evs)
        self.assertEqual(st["by_tag"], {"ai_security": 1, "ai_agent": 2})
        self.assertEqual(st["mentions_by_tag"], {"ai_security": 3, "ai_agent": 4})
        self.assertEqual(st["high_importance_by_tag"], {"ai_security": 1, "ai_agent": 1})

    def test_summary_carries_tag_stats(self):
        evs = [{"event_id": "e1", "category": "products_apps", "importance": 6,
                "mention_count": 1, "tags": ["coding_ai"], "sources": []}]
        summ = doc_model.build_summary("2026-11-19", evs, [], {"產品與應用": 1})
        self.assertEqual(summ["by_tag"], {"coding_ai": 1})
        self.assertEqual(summ["tags_version"], tags.TAGS_VERSION)
        self.assertEqual(summ["total_db"], 1)

if __name__ == "__main__":
    unittest.main()
