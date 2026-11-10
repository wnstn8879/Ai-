"""Native emulator QA using test accounts only; never needs an external AI key."""

import json
import os
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import Request, urlopen

ARTIFACTS = Path("/tmp/storyverse-android-qa")
ARTIFACTS.mkdir(exist_ok=True)
API = "http://127.0.0.1:8000"
PACKAGE = "com.storyverse.ai"
PASSWORD = "android-qa-test-password"


def api(path, method="GET", body=None, token=None):
    req = Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": "Bearer " + token} if token else {}),
        },
    )
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def adb(*args, binary=False):
    return subprocess.check_output(["adb", *args], timeout=45, text=not binary)


def screenshot(name):
    (ARTIFACTS / (name + ".png")).write_bytes(
        adb("exec-out", "screencap", "-p", binary=True)
    )


def hierarchy():
    adb("shell", "uiautomator", "dump", "/sdcard/storyverse-window.xml")
    raw = adb("shell", "cat", "/sdcard/storyverse-window.xml")
    (ARTIFACTS / "last-window.xml").write_text(raw)
    return ET.fromstring(raw)


def bounds(node):
    return [int(x) for x in re.findall(r"\d+", node.attrib["bounds"])]


def find(label, scroll=False, timeout=35):
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        tree = hierarchy()
        for node in tree.iter("node"):
            if label in (node.attrib.get("text"), node.attrib.get("content-desc")):
                x1, y1, x2, y2 = bounds(node)
                if x2 > x1 and y2 > y1:
                    return node
        if scroll:
            # Search down, then up; no device resolution assumptions beyond the emulator profile.
            if attempt < 10:
                adb("shell", "input", "swipe", "500", "1250", "500", "500", "180")
            else:
                adb("shell", "input", "swipe", "500", "500", "500", "1250", "180")
        attempt += 1
        time.sleep(0.4)
    raise AssertionError("Native element not found: " + label)


def tap(label, scroll=False):
    node = find(label, scroll)
    x1, y1, x2, y2 = bounds(node)
    adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
    time.sleep(0.4)


def keyboard_shown():
    dump = adb("shell", "dumpsys", "input_method")
    return "mInputShown=true" in dump or "isInputViewShown=true" in dump


def hide_keyboard():
    if keyboard_shown():
        adb("shell", "input", "keyevent", "BACK")
        time.sleep(0.3)


def wait_until(description, condition, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.5)
    raise AssertionError("Timed out: " + description)


def run(apk):
    # Both users and all story records exist only in this job's isolated SQLite database.
    stamp = uuid.uuid4().hex[:12]
    email = "android-owner-" + stamp + "@example.com"
    owner = api(
        "/auth/register",
        "POST",
        {"email": email, "password": PASSWORD, "display_name": "Android owner"},
    )
    peer = api(
        "/auth/register",
        "POST",
        {
            "email": "android-peer-" + stamp + "@example.com",
            "password": PASSWORD,
            "display_name": "Android peer",
        },
    )
    token = owner["access_token"]
    peer_token = peer["access_token"]
    title = "AndroidQAStory"
    room = api(
        "/rooms",
        "POST",
        {
            "title": title,
            "world_rules": "Keep the original timeline",
            "mode": "multiplayer",
        },
        token,
    )
    rid = room["id"]
    code = api("/rooms/" + rid + "/invitations", "POST", token=token)["code"]
    api("/invitations/join", "POST", {"code": code}, peer_token)
    api(
        "/rooms/" + rid + "/messages",
        "POST",
        {"actor": "Owner", "content": "Original message"},
        token,
    )
    adb("shell", "settings", "put", "secure", "show_ime_with_hard_keyboard", "1")
    adb("install", "-r", "-t", str(apk))
    adb("reverse", "tcp:8081", "tcp:8081")
    adb("reverse", "tcp:8000", "tcp:8000")
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
    find("이메일", timeout=150)
    tap("이메일")
    adb("shell", "input", "text", email)
    hide_keyboard()
    tap("비밀번호 (10자 이상)", True)
    adb("shell", "input", "text", PASSWORD)
    hide_keyboard()
    tap("로그인", True)
    find(title, True, 60)
    # A fresh process must restore its secure session without another login.
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
    find(title, True, 90)
    tap("마지막 장면에서 이어하기", True)
    tap("행동이나 대사 입력", True)
    adb("shell", "input", "text", "AndroidNativeSmoke")
    wait_until("native keyboard visible", keyboard_shown)
    node = find("행동이나 대사 입력")
    assert (
        node.attrib.get("text") == "AndroidNativeSmoke"
    ), "Native text input did not retain typed message"
    x1, y1, x2, y2 = bounds(node)
    assert x2 > x1 and y2 - y1 >= 30, "Input was clipped"
    screenshot("01-keyboard-and-input")
    hide_keyboard()
    tap("참가자에게 메시지 보내기", True)
    wait_until(
        "native message persisted",
        lambda: any(
            m["content"] == "AndroidNativeSmoke"
            for m in api("/rooms/" + rid, token=token)["messages"]
        ),
    )
    tap("현재 장면 공용 저장", True)
    saved = wait_until(
        "shared checkpoint",
        lambda: next(
            (
                s
                for s in api("/rooms/" + rid + "/saves", token=token)
                if s["scope"] == "shared"
            ),
            None,
        ),
    )
    # Preserve a later scene to prove that the original is not truncated by restore.
    api(
        "/rooms/" + rid + "/messages",
        "POST",
        {"actor": "Owner", "content": "Later original scene"},
        token,
    )
    tap("이 지점으로 공용 복원 제안", True)
    proposal = wait_until(
        "restore proposal",
        lambda: next(
            iter(api("/rooms/" + rid + "/restore-proposals", token=token)), None
        ),
    )
    assert (
        proposal["status"] == "pending"
    ), "A second participant must explicitly approve"
    api(
        "/rooms/" + rid + "/restore-proposals/" + proposal["id"] + "/vote",
        "POST",
        {"accept": True},
        peer_token,
    )
    tap("전원 동의한 공용 복원 실행", True)
    child = wait_until(
        "restored multiplayer room",
        lambda: next(
            (r for r in api("/rooms", token=token) if r["parent_room_id"] == rid), None
        ),
    )
    assert (
        child["mode"] == "multiplayer"
        and len(child["messages"]) == saved["message_index"]
    )
    assert (
        len(api("/rooms/" + rid, token=token)["messages"]) == saved["message_index"] + 1
    )
    assert len(api("/rooms/" + child["id"] + "/members", token=peer_token)) == 2
    find(title + " · 공용 복원", True, 60)
    screenshot("02-restored-multiplayer-room")
    metro = Path("/tmp/storyverse-metro.log").read_text()
    assert "Encountered two children" not in metro, "Duplicate native component keys"
    report = {
        "result": "passed",
        "checks": [
            "native login",
            "secure session restored after process restart",
            "story load",
            "keyboard and text input",
            "native participant message persisted",
            "native shared checkpoint",
            "explicit second-account approval",
            "native unanimous restore",
            "original history retained",
            "both participants retained",
        ],
        "device": adb("shell", "getprop", "ro.product.model").strip(),
        "api_level": adb("shell", "getprop", "ro.build.version.sdk").strip(),
        "physical_device_tested": False,
    }
    (ARTIFACTS / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print("Android emulator QA passed: " + ", ".join(report["checks"]))


if __name__ == "__main__":
    try:
        run(Path(sys.argv[1]))
    except Exception:
        try:
            screenshot("failure")
        except Exception:
            pass
        raise
    finally:
        try:
            (ARTIFACTS / "logcat.txt").write_text(adb("logcat", "-d", "-t", "1500"))
        except Exception:
            pass
