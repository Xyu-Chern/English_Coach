"""Deliver an authenticated private Site job to the existing loopback coach."""

import os
import time
import httpx

SITE = "https://phrase-room-coach.focalmeadow5.chatgpt.site"
LOCAL = "http://127.0.0.1:8787/api/search"


def main():
    headers = {
        "OAI-Sites-Authorization": "Bearer " + os.environ["COACH_SITE_ACCESS"],
        "x-coach-relay": os.environ["COACH_RELAY_SECRET"],
    }
    with httpx.Client(
        base_url=SITE, headers=headers, timeout=20, follow_redirects=False
    ) as site:
        while True:
            try:
                response = site.post("/api/relay/claim")
                response.raise_for_status()
                job = response.json()
                if not job.get("id"):
                    time.sleep(6)
                    continue
                try:
                    local_headers = {
                        "X-Coach-Code": os.environ.get("COACH_PAIR_CODE", "")
                    }
                    answer = httpx.post(
                        LOCAL,
                        json={k: job[k] for k in ("question", "context")},
                        headers=local_headers,
                        timeout=1750,
                        trust_env=False,
                    )
                    result, status = answer.json(), answer.status_code
                except (httpx.HTTPError, ValueError):
                    result, status = {"detail": "coach_unavailable"}, 503
                body = {
                    "id": job["id"],
                    "lease": job["lease"],
                    "result": result,
                    "status": status,
                }
                for delay in (0, 3, 10, 25, 45):
                    time.sleep(delay)
                    try:
                        res = site.post("/api/relay/finish", json=body)
                        if res.is_success or res.status_code == 409:
                            break
                    except httpx.HTTPError:
                        pass
            except (httpx.HTTPError, ValueError):
                time.sleep(15)


if __name__ == "__main__":
    main()
