"""发布约束：正式模式必须有 Key，mock 只能显式开启。"""

from __future__ import annotations

import pytest

from app import config


def test_llm_requires_key(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "llm")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "ALLOW_MOCK", False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        config.validate_runtime()


def test_placeholder_key_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "llm")
    monkeypatch.setattr(config, "LLM_API_KEY", "sk-...")
    monkeypatch.setattr(config, "ALLOW_MOCK", False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        config.validate_runtime()


def test_mock_requires_explicit_allow(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "mock")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "ALLOW_MOCK", False)
    with pytest.raises(RuntimeError, match="mock"):
        config.validate_runtime()


def test_mock_allowed_for_tests(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "mock")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "ALLOW_MOCK", True)
    config.validate_runtime()
