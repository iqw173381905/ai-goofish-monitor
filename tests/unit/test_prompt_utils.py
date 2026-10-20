import asyncio
import types

import pytest

import src.prompt_utils as prompt_utils
from src.services.ai_response_parser import EmptyAIResponseError


def test_generate_criteria_closes_ai_client_after_success(monkeypatch, tmp_path):
    close_state = {"closed": False}
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")

    class FakeAIClient:
        def is_available(self):
            return True

        def refresh(self):
            raise AssertionError("refresh should not be called")

        async def _call_ai(self, *_args, **_kwargs):
            return "generated criteria"

        async def close(self):
            close_state["closed"] = True

    monkeypatch.setattr(prompt_utils, "AIClient", FakeAIClient)

    result = asyncio.run(
        prompt_utils.generate_criteria("need a gpu", str(reference_file))
    )

    assert result == "generated criteria"
    assert close_state["closed"] is True


def test_generate_criteria_drops_think_blocks_and_raises_output_limit(monkeypatch, tmp_path):
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")
    captured = {}

    class FakeAIClient:
        def is_available(self):
            return True

        def refresh(self):
            raise AssertionError("refresh should not be called")

        async def _call_ai(self, *_args, **kwargs):
            captured.update(kwargs)
            return "<think>先分析需求</think>\n\n一票否决：电池健康度不足"

        async def close(self):
            return None

    monkeypatch.setattr(prompt_utils, "AIClient", FakeAIClient)

    result = asyncio.run(
        prompt_utils.generate_criteria("need a watch", str(reference_file))
    )

    assert result == "一票否决：电池健康度不足"
    assert captured["max_output_tokens"] == prompt_utils.CRITERIA_MAX_OUTPUT_TOKENS
    assert captured["max_output_tokens"] > 800


def test_generate_criteria_rejects_truncated_think_block(monkeypatch, tmp_path):
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")

    class FakeAIClient:
        def is_available(self):
            return True

        def refresh(self):
            raise AssertionError("refresh should not be called")

        async def _call_ai(self, *_args, **_kwargs):
            return "<think>输出到这里被截断"

        async def close(self):
            return None

    monkeypatch.setattr(prompt_utils, "AIClient", FakeAIClient)

    with pytest.raises(RuntimeError, match="思考过程占满了输出长度"):
        asyncio.run(prompt_utils.generate_criteria("need a watch", str(reference_file)))


def test_generate_criteria_closes_ai_client_after_ai_failure(monkeypatch, tmp_path):
    close_state = {"closed": False}
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")

    class FakeAIClient:
        def is_available(self):
            return True

        def refresh(self):
            raise AssertionError("refresh should not be called")

        async def _call_ai(self, *_args, **_kwargs):
            raise EmptyAIResponseError("AI响应内容为空。")

        async def close(self):
            close_state["closed"] = True

    monkeypatch.setattr(prompt_utils, "AIClient", FakeAIClient)

    with pytest.raises(EmptyAIResponseError, match="AI响应内容为空"):
        asyncio.run(prompt_utils.generate_criteria("need a gpu", str(reference_file)))

    assert close_state["closed"] is True


class _FakeRawCompletions:
    def __init__(self, text=None, exc=None):
        self.text = text
        self.exc = exc

    async def create(self, **kwargs):
        if self.exc is not None:
            raise self.exc
        message = types.SimpleNamespace(content=self.text)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _fake_chain_client(text=None, exc=None):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=_FakeRawCompletions(text, exc))
    )


def test_generate_criteria_uses_failover_chain_first(monkeypatch, tmp_path):
    """有档案链时走链，不再构造旧的 .env 默认 AIClient。"""
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")
    chain = [("gpt-4o档案", _fake_chain_client(text="chain criteria"), "gpt-4o")]
    monkeypatch.setattr(prompt_utils, "_resolve_criteria_failover_chain", lambda: chain)

    def _no_legacy_client(*_args, **_kwargs):
        raise AssertionError("legacy AIClient must not be constructed when chain exists")

    monkeypatch.setattr(prompt_utils, "AIClient", _no_legacy_client)

    result = asyncio.run(
        prompt_utils.generate_criteria("need a watch", str(reference_file))
    )
    assert result == "chain criteria"


def test_generate_criteria_fails_over_to_next_profile(monkeypatch, tmp_path):
    """首个档案失败时自动转移到下一个档案。"""
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")
    chain = [
        ("档案A", _fake_chain_client(exc=TimeoutError("boom")), "model-a"),
        ("档案B", _fake_chain_client(text="from backup"), "model-b"),
    ]
    monkeypatch.setattr(prompt_utils, "_resolve_criteria_failover_chain", lambda: chain)

    result = asyncio.run(
        prompt_utils.generate_criteria("need a watch", str(reference_file))
    )
    assert result == "from backup"


def test_generate_criteria_chain_all_fail_raises_last_error(monkeypatch, tmp_path):
    """链上全部失败时抛出最后一个异常。"""
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")
    chain = [
        ("档案A", _fake_chain_client(exc=TimeoutError("first")), "model-a"),
        ("档案B", _fake_chain_client(exc=ValueError("second")), "model-b"),
    ]
    monkeypatch.setattr(prompt_utils, "_resolve_criteria_failover_chain", lambda: chain)

    with pytest.raises(ValueError, match="second"):
        asyncio.run(prompt_utils.generate_criteria("need a watch", str(reference_file)))


def test_generate_criteria_falls_back_to_legacy_when_chain_empty(monkeypatch, tmp_path):
    """链为空时回退到旧的 .env 默认配置路径。"""
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")

    class FakeAIClient:
        def is_available(self):
            return True

        async def _call_ai(self, *_args, **_kwargs):
            return "legacy criteria"

        async def close(self):
            return None

    monkeypatch.setattr(prompt_utils, "_resolve_criteria_failover_chain", lambda: [])
    monkeypatch.setattr(prompt_utils, "AIClient", FakeAIClient)

    result = asyncio.run(
        prompt_utils.generate_criteria("need a watch", str(reference_file))
    )
    assert result == "legacy criteria"


def test_split_keywords_drops_required_and_keeps_optional():
    """必含关键词不由 AI 生成：REQUIRED 段写了也丢弃；可选正常解析。"""
    text = (
        "标准正文\n"
        "[KEYWORDS_REQUIRED]\n"
        "Apple Watch\nSeries 3\n"
        "[KEYWORDS_OPTIONAL]\n"
        "蜂窝版\n国行\n42mm\n表带齐全\n无拆修\n续航好\n"
        "[END]\n"
    )
    criteria, required, optional = prompt_utils.split_criteria_and_keywords(text)
    assert criteria == "标准正文"
    assert required == []
    assert optional == ["蜂窝版", "国行", "42mm", "表带齐全", "无拆修", "续航好"]


def test_split_keywords_optional_only_marker_and_dedup():
    """只有 OPTIONAL 标记时也能解析，且可选关键词去重保序。"""
    text = "正文\n[KEYWORDS_OPTIONAL]\n国行\n国行\n 蜂窝 \n[END]"
    criteria, required, optional = prompt_utils.split_criteria_and_keywords(text)
    assert criteria == "正文"
    assert required == []
    assert optional == ["国行", "蜂窝"]


def test_split_keywords_no_markers_returns_text_unchanged():
    criteria, required, optional = prompt_utils.split_criteria_and_keywords("纯标准文本")
    assert criteria == "纯标准文本"
    assert required == []
    assert optional == []
