"""Outbound-only authenticated relay; no backend ports are published to the internet."""

import concurrent.futures
import getpass
import json
import time
import re
import httpx

cfg = json.loads(getpass.getpass("Private relay configuration (hidden): "))
site = cfg["site"].rstrip("/")
headers = {
    "OAI-Sites-Authorization": "Bearer " + cfg["bypass"],
    "x-imagine-relay-key": cfg["key"],
    "Content-Type": "application/json",
}


def execute(job):
    auth = {
        "x-imagine-service-key": cfg["key"],
        "x-imagine-visitor": job["visitor"],
        "Content-Type": "application/json",
    }

    def local(path, method="GET", body=None):
        with httpx.Client(timeout=190, follow_redirects=False) as client:
            response = client.request(
                method, "http://127.0.0.1:8111" + path, headers=auth, content=body
            )
            return response.status_code, response.json()

    try:
        status, data = local(job["path"], job["method"], job.get("body"))
        updates = []
        if (
            200 <= status < 300
            and job["method"] != "GET"
            and "/memory/" not in job["path"]
            and "/writer" not in job["path"]
        ):
            paths = {"/library"}
            m = re.match(r"^/rooms/([A-Za-z0-9-]+)", job["path"])
            if m:
                paths.update(
                    {
                        "/rooms/" + m.group(1) + "/chapters",
                        "/rooms/" + m.group(1) + "/saves",
                    }
                )
            if isinstance(data, dict) and data.get("narrative_format"):
                paths.update(
                    {
                        "/rooms/" + data["id"] + "/chapters",
                        "/rooms/" + data["id"] + "/saves",
                    }
                )
            for path in paths:
                code, payload = local(path)
                if code == 200:
                    updates.append({"path": path, "data": payload})
        result = {
            "id": job["id"],
            "status": status,
            "data": data,
            "cache_updates": updates,
        }
    except Exception:
        result = {
            "id": job["id"],
            "status": 502,
            "data": {
                "detail": "이야기 서버 연결이 지연됐습니다. 저장 상태를 확인한 뒤 다시 시도해주세요."
            },
        }
    # Finishing is idempotent; never automatically repeat a model request.
    for _ in range(3):
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(site + "/relay/complete", headers=headers, json=result)
                if r.status_code in (200, 404):
                    break
        except httpx.HTTPError:
            pass
        time.sleep(2)


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    running = set()
    print("Authenticated IMAGINE relay ready", flush=True)
    while True:
        try:
            running = {f for f in running if not f.done()}
            if len(running) >= 4:
                time.sleep(0.5)
                continue
            with httpx.Client(timeout=15) as client:
                # A heartbeat is advertised only when both real services respond.
                client.get("http://127.0.0.1:8111/health").raise_for_status()
                client.get("http://127.0.0.1:11434/api/version").raise_for_status()
                response = client.post(site + "/relay/poll", headers=headers, json={})
                response.raise_for_status()
                jobs = response.json()["jobs"]
            for job in jobs:
                running.add(pool.submit(execute, job))
        except Exception as e:
            print("Relay reconnecting (" + type(e).__name__ + ")", flush=True)
        time.sleep(1.5)
