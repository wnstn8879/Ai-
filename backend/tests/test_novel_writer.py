import asyncio
import time
import threading
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import select, func
from app.database import Session, NovelWriter, Message
from app.novel_writer import split_draft


def book(client):
    return client.post(
        "/rooms",
        json={
            "title": "계속 펼쳐지는 세계",
            "world_rules": "김치 내공의 우주 무림에서 동생을 찾는다.",
            "narrative_format": "novel",
        },
    ).json()["id"]


def wait_for(client, path, predicate, seconds=5):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        response = client.get(path + "/writer")
        assert response.status_code == 200, response.text
        state = response.json()
        if predicate(state):
            return state
        time.sleep(0.02)
    raise AssertionError(state)


def test_autonomous_sections_and_one_time_direction_without_repeated_reader_input(
    account,
):
    a, _ = account()
    rid = book(a)
    path = "/rooms/" + rid
    release = threading.Event()
    calls = []

    async def model(prompt):
        calls.append(prompt)
        yield {"text": "첫 장면의 긴 초안이 저장된다."}
        if len(calls) == 1:
            while not release.is_set():
                await asyncio.sleep(0.01)
        yield {"text": " 인물은 스스로 다음 사건으로 향했다."}
        yield {"finish_reason": "stop"}

    with a, patch("app.novel_writer.stream_complete", side_effect=model):
        response = a.post(
            path + "/writer/start", json={"request_id": "start-auto", "sections": 3}
        )
        assert response.status_code == 200, response.text
        wait_for(a, path, lambda s: bool(s["draft"]))
        direction = {
            "request_id": "one-direction",
            "content": "이번 장면에서는 서연이 동료를 믿게 해줘.",
        }
        assert a.post(path + "/writer/direction", json=direction).status_code == 200
        assert a.post(path + "/writer/direction", json=direction).status_code == 200
        release.set()
        state = wait_for(a, path, lambda s: s["status"] == "paused")
        assert state["completed"] == 3 and state["message_count"] == 6
        assert len(calls) == 3
        assert "동료를 믿게" in calls[1][-1]["content"]
        assert "동료를 믿게" not in calls[2][-1]["content"]
        assert state["pending_direction"] == "" and state["draft"] == ""
        assert (
            a.post(
                path + "/writer/start", json={"request_id": "start-auto", "sections": 3}
            ).status_code
            == 200
        )
        assert len(calls) == 3
        assert (
            a.post(
                path + "/writer/start", json={"request_id": "start-auto", "sections": 4}
            ).status_code
            == 409
        )
        assert len(a.get(path).json()["messages"]) == 6
        assert "AUTONOMOUS NOVEL" in calls[0][0]["content"]
        assert "at most 300" not in calls[0][0]["content"]


def test_pause_recovers_draft_and_resume_continues_prefix_and_rejects_foreign_user(
    account,
):
    a, _ = account()
    b, _ = account()
    rid = book(a)
    path = "/rooms/" + rid
    calls = []

    async def model(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            yield {"text": "달빛 아래 동생의 편지가 열렸다. "}
            while True:
                await asyncio.sleep(0.01)
        yield {"text": "서연은 편지 속 좌표를 따라 발걸음을 옮겼다."}
        yield {"finish_reason": "stop"}

    with a, patch("app.novel_writer.stream_complete", side_effect=model):
        a.post(path + "/writer/start", json={"request_id": "draft-one", "sections": 1})
        state = wait_for(a, path, lambda s: bool(s["draft"]))
        assert (
            a.post(path + "/writer/pause", json={"run_id": state["run_id"]}).status_code
            == 200
        )
        draft = a.get(path + "/writer").json()["draft"]
        assert draft == "달빛 아래 동생의 편지가 열렸다. "
        assert a.get(path).json()["messages"] == []
        for endpoint, method, body in [
            ("/writer", "GET", None),
            ("/writer/pause", "POST", {}),
            ("/writer/start", "POST", {"request_id": "other"}),
        ]:
            assert b.request(method, path + endpoint, json=body).status_code == 404
        a.post(
            path + "/writer/start", json={"request_id": "draft-resume", "sections": 1}
        )
        final = wait_for(
            a, path, lambda s: s["status"] == "paused" and s["completed"] == 1
        )
        prose = a.get(path).json()["messages"][-1]["content"]
        assert prose == draft + "서연은 편지 속 좌표를 따라 발걸음을 옮겼다."
        assert any(m["content"] == draft for m in calls[1])
        assert final["draft"] == ""
        assert (
            a.post(path + "/writer/pause", json={"run_id": state["run_id"]}).status_code
            == 409
        )


def test_major_crossroad_stops_before_next_installment_and_marker_is_metadata(account):
    a, _ = account()
    rid = book(a)
    path = "/rooms/" + rid
    calls = []

    async def model(prompt):
        calls.append(prompt)
        yield {"text": "좀비는 동생을 살릴 좌표를 내밀었다.\n[IMAGINE_"}
        yield {
            "text": "BRANCH]동료를 믿고 좌표를 따라갈까요, 약속을 지킬 다른 길을 찾을까요?"
        }
        yield {"finish_reason": "stop"}

    with a, patch("app.novel_writer.stream_complete", side_effect=model):
        a.post(path + "/writer/start", json={"request_id": "crossroad", "sections": 4})
        state = wait_for(a, path, lambda s: s["status"] == "choice")
        assert len(calls) == 1 and state["completed"] == 1
        assert "동료를 믿고" in state["question"]
        assert (
            a.get(path).json()["messages"][-1]["content"]
            == "좀비는 동생을 살릴 좌표를 내밀었다."
        )
        assert split_draft("본문\n[IMAGINE_")[0].strip() == "본문"


def test_stream_failure_and_changed_history_preserve_draft_without_committing_stale_prose(
    account,
):
    a, _ = account()
    rid = book(a)
    path = "/rooms/" + rid
    release = threading.Event()

    async def broken(prompt):
        yield {"text": "아직 완성되지 않은 초안."}
        raise HTTPException(502, "모델 연결 실패")

    with a, patch("app.novel_writer.stream_complete", side_effect=broken):
        a.post(path + "/writer/start", json={"request_id": "broken", "sections": 1})
        state = wait_for(a, path, lambda s: s["status"] == "error")
        assert state["draft"] == "아직 완성되지 않은 초안."
        assert a.get(path).json()["messages"] == []

    async def delayed(prompt):
        yield {"text": " 다음 문장."}
        while not release.is_set():
            await asyncio.sleep(0.01)
        yield {"finish_reason": "stop"}

    with a, patch("app.novel_writer.stream_complete", side_effect=delayed):
        a.post(path + "/writer/start", json={"request_id": "conflict", "sections": 1})
        wait_for(a, path, lambda s: "다음" in s["draft"])
        a.post(
            path + "/messages",
            json={"actor": "작가", "content": "다른 편집이 저장됐다."},
        )
        release.set()
        state = wait_for(a, path, lambda s: s["status"] == "error")
        assert "바뀌었습니다" in state["error"] and state["draft"]
        assert len(a.get(path).json()["messages"]) == 1


def test_lost_reader_lease_pauses_and_does_not_restart_on_status_reads(account):
    a, _ = account()
    rid = book(a)
    path = "/rooms/" + rid

    async def delayed(prompt):
        yield {"text": "연결이 끊겨도 남을 초안."}
        while True:
            await asyncio.sleep(0.01)

    with a, patch("app.novel_writer.stream_complete", side_effect=delayed):
        a.post(path + "/writer/start", json={"request_id": "lease", "sections": 1})
        state = wait_for(a, path, lambda s: bool(s["draft"]))
        with Session.begin() as db:
            db.get(NovelWriter, rid).lease_until = int(time.time()) - 1
        paused = a.get(path + "/writer").json()
        assert paused["status"] == "paused" and paused["draft"]
        assert a.get(path + "/writer").json()["status"] == "paused"
        a.post(path + "/writer/pause", json={"run_id": state["run_id"]})


def test_continuous_reader_goes_past_batch_size_until_real_question(account):
    a, _ = account()
    rid = book(a)
    path = "/rooms/" + rid
    calls = []

    async def model(prompt):
        calls.append(prompt)
        yield {"text": "인물은 스스로 사건과 관계를 이어 나갔다."}
        if len(calls) == 3:
            yield {
                "text": "\n[IMAGINE_BRANCH]동료의 손을 잡으면 약속을 지킬 수 있을까요?"
            }
        yield {"finish_reason": "stop"}

    with a, patch("app.novel_writer.stream_complete", side_effect=model):
        a.post(
            path + "/writer/start",
            json={"request_id": "continuous", "sections": 1, "continuous": True},
        )
        state = wait_for(a, path, lambda s: s["status"] == "choice")
        assert state["completed"] == 3 and len(calls) == 3
        assert a.get(path + "/chapters").json()["message_count"] == 6


def test_continuous_reading_obeys_daily_budget_and_keeps_finished_text(
    account, monkeypatch
):
    a, _ = account()
    rid = book(a)
    path = "/rooms/" + rid
    calls = []
    monkeypatch.setenv("AI_USER_DAILY_LIMIT", "1")

    async def model(prompt):
        calls.append(prompt)
        yield {"text": "완성된 첫 부분은 한도 뒤에도 남는다."}
        yield {"finish_reason": "stop"}

    with a, patch("app.novel_writer.stream_complete", side_effect=model):
        a.post(
            path + "/writer/start", json={"request_id": "budget", "continuous": True}
        )
        state = wait_for(a, path, lambda s: s["status"] == "error")
        assert len(calls) == 1 and state["completed"] == 1
        assert (
            a.get(path).json()["messages"][-1]["content"]
            == "완성된 첫 부분은 한도 뒤에도 남는다."
        )
