import pytest
from fastapi import HTTPException
from app.context_budget import pack, cost


def test_unicode_context_keeps_canon_and_new_instruction_and_reports_omissions():
    canon = "확정: 서연은 살아 있다. 💫"
    history = [
        {"role": "assistant", "content": "세계가 움직였다. " * 120} for _ in range(100)
    ]
    prompt, report = pack(canon, history, "동생과의 관계를 이어줘", [])
    assert (
        prompt[0]["content"] == canon
        and prompt[-1]["content"] == "동생과의 관계를 이어줘"
    )
    assert cost(prompt) == report["input_utf8_bound"] <= report["input_budget"]
    assert report["history_messages_not_in_recent"] > 90
    assert all(m["content"] == history[0]["content"] for m in prompt[1:-1])


def test_source_quote_budget_and_recent_dedup_do_not_change_source_text():
    source = {
        "message_id": "saved-source",
        "actor": "AI",
        "position": 1,
        "start": 0,
        "end": 12,
        "quote": "💫 지난 약속이다.",
    }
    prompt, report = pack(
        "확정 설정",
        [{"role": "assistant", "content": "최근 사건"}],
        "약속을 떠올려줘",
        [source],
    )
    assert source["quote"] in prompt[0]["content"] and report["sources"][0] == source
    _, dedup = pack(
        "확정 설정",
        [{"role": "assistant", "content": "최근 사건"}],
        "방향",
        [source],
        positions=[1],
    )
    assert dedup["sources"] == []


def test_invalid_model_window_and_oversized_latest_record_fail_explicitly(monkeypatch):
    monkeypatch.setenv("AI_CONTEXT_WINDOW_TOKENS", "wrong")
    with pytest.raises(HTTPException) as invalid:
        pack("규칙", [], "시작", [])
    assert invalid.value.status_code == 503
    monkeypatch.setenv("AI_CONTEXT_WINDOW_TOKENS", "8192")
    with pytest.raises(HTTPException) as large:
        pack("규칙", [{"role": "assistant", "content": "가" * 10000}], "시작", [])
    assert large.value.status_code == 422
