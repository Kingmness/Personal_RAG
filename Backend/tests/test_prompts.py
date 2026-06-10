# -*- coding: utf-8 -*-
from prompts import build_answer_prompt, build_user_prompt


class TestBuildAnswerPrompt:
    def test_number_type(self):
        result = build_answer_prompt("number")
        assert "system" in result
        assert "数值" in result["system"] or "number" in result["system"].lower()

    def test_name_type(self):
        result = build_answer_prompt("name")
        assert "名称" in result["system"]

    def test_boolean_type(self):
        result = build_answer_prompt("boolean")
        assert "true" in result["system"] or "false" in result["system"]

    def test_list_type(self):
        result = build_answer_prompt("list")
        assert "列表" in result["system"] or "条目" in result["system"]

    def test_text_type(self):
        result = build_answer_prompt("text")
        assert "开放文本" in result["system"] or "自然语言" in result["system"]

    def test_unknown_type_falls_back_to_text(self):
        result = build_answer_prompt("unknown")
        assert "开放文本" in result["system"] or "自然语言" in result["system"]

    def test_contains_json_format(self):
        for ptype in ["number", "name", "boolean", "list", "text"]:
            result = build_answer_prompt(ptype)
            assert "step_by_step_analysis" in result["system"]
            assert "final_answer" in result["system"]


class TestBuildUserPrompt:
    def test_contains_question_and_context(self):
        prompt = build_user_prompt("测试问题", "测试上下文")
        assert "测试问题" in prompt
        assert "测试上下文" in prompt

    def test_has_delimiters(self):
        prompt = build_user_prompt("Q", "C")
        assert '"""' in prompt
