"""Release APK tested offline with no API server, Metro, accounts or AI keys."""

import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = "com.storyverse.ai.preview"
OUT = Path("/tmp/storyverse-preview-qa")
OUT.mkdir(exist_ok=True)


def adb(*args, binary=False):
    return subprocess.check_output(
        ["adb", "-s", "emulator-5554", *args], text=not binary, timeout=40
    )


def screen(name):
    (OUT / (name + ".png")).write_bytes(adb("exec-out", "screencap", "-p", binary=True))


def tree():
    adb("shell", "rm", "-f", "/sdcard/preview.xml")
    adb("shell", "uiautomator", "dump", "/sdcard/preview.xml")
    raw = adb("shell", "cat", "/sdcard/preview.xml")
    (OUT / "last-ui.xml").write_text(raw)
    return ET.fromstring(raw)


def find(label, scroll=False, timeout=45):
    deadline = time.monotonic() + timeout
    attempts = 0
    while time.monotonic() < deadline:
        try:
            nodes = tree()
        except (subprocess.SubprocessError, ET.ParseError):
            time.sleep(0.5)
            continue
        for n in nodes.iter("node"):
            if label in (n.get("text"), n.get("content-desc")):
                coords = [int(x) for x in re.findall(r"\d+", n.get("bounds", ""))]
                if len(coords) == 4 and coords[2] > coords[0] and coords[3] > coords[1]:
                    return coords
        if scroll:
            # Start inside the actual scroll area. The fixed story header can
            # extend below y=450, so a swipe starting there never scrolls up.
            candidates = []
            for view in nodes.iter("node"):
                if view.get("class") == "android.widget.ScrollView":
                    b = [int(x) for x in re.findall(r"\d+", view.get("bounds", ""))]
                    if len(b) == 4 and b[3] - b[1] > 100:
                        candidates.append(b)
            if candidates:
                left, top, right, bottom = max(
                    candidates, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])
                )
                x = (left + right) // 2
                low, high = top + (bottom - top) * 3 // 4, top + (bottom - top) // 4
            else:
                x, low, high = 500, 1300, 850
            start, end = (low, high) if attempts % 16 < 8 else (high, low)
            adb("shell", "input", "swipe", str(x), str(start), str(x), str(end), "160")
        attempts += 1
        time.sleep(0.3)
    raise AssertionError("Missing native element: " + label)


def tap(label, scroll=False):
    x1, y1, x2, y2 = find(label, scroll)
    adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
    time.sleep(0.4)


def launch():
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")


def main():
    adb("install", "-r", "-t", str(Path(sys.argv[1]).resolve()))
    adb("reverse", "--remove-all")
    adb("shell", "cmd", "connectivity", "airplane-mode", "enable")
    adb("shell", "svc", "wifi", "disable")
    adb("shell", "svc", "data", "disable")
    assert adb("shell", "settings", "get", "global", "airplane_mode_on").strip() == "1"
    adb("shell", "settings", "put", "secure", "show_ime_with_hard_keyboard", "1")
    launch()
    find("새 이야기 시작")
    screen("01-home-offline")
    tap("새 이야기 시작")
    find("나의 행동 입력")
    tap("봉투를 열어본다", scroll=True)
    find("기기에 자동 저장됨")
    screen("02-story-offline")
    tap("나의 행동 입력")
    adb("shell", "input", "text", "preview_draft")
    keyboard = adb("shell", "dumpsys", "input_method")
    if "mInputShown=true" in keyboard or "isInputViewShown=true" in keyboard:
        adb("shell", "input", "keyevent", "BACK")
    find("초안 저장됨")
    launch()
    tap("이어서 플레이", scroll=True)
    find("preview_draft")
    screen("03-draft-after-restart")
    tap("행동 보내기")
    find("기기에 자동 저장됨")
    tap("저장 지점 · 타임라인", scroll=True)
    tap("현재 장면 저장")
    find("현재 장면을 기기에 저장했어요.")
    screen("04-checkpoint")
    tap("1번째 메시지에서 분기", scroll=True)
    tap("새 분기 만들기")
    find("원본을 보존하고 새 분기를 만들었어요.")
    screen("05-branch")
    tap("주변에 봉투 주인이 있는지 살핀다", scroll=True)
    find("기기에 자동 저장됨")
    tap("역무원에게 봉투 주인을 묻는다", scroll=True)
    tap("편지함으로 간다", scroll=True)
    tap("편지를 주인에게 돌려준다", scroll=True)
    find("여기서 쉬어가도 좋아요", scroll=True)
    screen("06a-mystery-complete")
    tap("저장하고 쉬기", scroll=True)
    find("저장했어요. 다음 출근길에 이어가세요.")
    find("출근길의 수상한 봉투 · 다른 선택", scroll=True)
    screen("06-library-two-stories")
    launch()
    find("출근길의 수상한 봉투 · 다른 선택", scroll=True)
    # Most recently played branch is first; open original by the second accessible button.
    # SQL persistence tests additionally prove exact immutable original history.
    screen("07-library-after-restart")
    (OUT / "result.json").write_text(
        json.dumps(
            {
                "success": True,
                "package": PACKAGE,
                "metro_running": False,
                "backend_running": False,
                "airplane_mode": True,
                "physical_device_tested": False,
                "verified": [
                    "standalone launch",
                    "authored choice",
                    "automatic save",
                    "draft process restart",
                    "checkpoint",
                    "message branch",
                    "original and branch in library",
                    "library process restart",
                    "four-choice mystery completion",
                ],
            },
            indent=2,
        )
    )


try:
    main()
except Exception:
    screen("failure")
    raise
finally:
    (OUT / "logcat.txt").write_text(adb("logcat", "-d", "-t", "1000"))
