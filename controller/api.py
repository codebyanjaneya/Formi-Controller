"""HTTP client for the simulator. The controller's ONLY window on the world.

Transport errors and 5xx are retried with backoff; 4xx raise ApiError with the
sim's structured {error, detail} body so callers can branch on error codes.
"""
import json
import logging
import time

import httpx

log = logging.getLogger("api")

RETRIES = 4
BACKOFF = 0.5


class ApiError(Exception):
    def __init__(self, status: int, error: str, detail=None):
        super().__init__(f"{status} {error}: {detail}")
        self.status = status
        self.error = error
        self.detail = detail


class Sim:
    def __init__(self, base_url: str):
        self.c = httpx.Client(base_url=base_url, timeout=120)

    def _req(self, method: str, path: str, body=None, params=None) -> httpx.Response:
        for attempt in range(RETRIES):
            try:
                r = self.c.request(method, path, json=body, params=params)
            except httpx.TransportError as e:
                if attempt == RETRIES - 1:
                    raise
                log.warning("transport error %s %s: %s; retrying", method, path, e)
                time.sleep(BACKOFF * 2**attempt)
                continue
            if r.status_code >= 500:
                if attempt == RETRIES - 1:
                    raise ApiError(r.status_code, "server_error", r.text[:200])
                time.sleep(BACKOFF * 2**attempt)
                continue
            if r.status_code >= 400:
                try:
                    j = r.json()
                except json.JSONDecodeError:
                    j = {}
                raise ApiError(r.status_code, j.get("error", "http_error"), j.get("detail"))
            return r
        raise AssertionError("unreachable")

    def _get(self, path, params=None):
        return self._req("GET", path, params=params).json()

    # --- world ---
    def state(self) -> dict:
        return self._get("/sim/state")

    def advance(self, minutes: int) -> dict:
        return self._req("POST", "/sim/advance", {"minutes": minutes}).json()

    def list_chunks(self, kind: str = "events", after: int | None = None) -> list:
        params = {"kind": kind}
        if after is not None:
            params["after"] = after
        return self._get("/events/chunks", params)

    def chunk_lines(self, n: int) -> list[str]:
        return self._req("GET", f"/events/chunks/{n}").text.splitlines()

    # --- policy & config ---
    def workflows(self) -> list:
        return self._get("/workflows")

    def get_config(self, wid: str) -> dict:
        return self._get(f"/workflows/{wid}/config")

    def config_history(self, wid: str) -> list:
        return self._get(f"/workflows/{wid}/config/history")

    # --- governance ---
    def post_approval(self, body: dict) -> dict:
        return self._req("POST", "/approvals", body).json()

    def get_approval(self, aid: str) -> dict:
        return self._get(f"/approvals/{aid}")

    def list_approvals(self, wid: str | None = None, status: str | None = None) -> list:
        params = {}
        if wid:
            params["workflow_id"] = wid
        if status:
            params["status"] = status
        return self._get("/approvals", params)

    def apply(self, wid: str, approval_id: str) -> dict:
        return self._req("POST", f"/workflows/{wid}/apply", {"approval_id": approval_id}).json()

    def put_config(self, wid: str, body: dict) -> dict:
        return self._req("PUT", f"/workflows/{wid}/config", body).json()

    # --- credits ---
    def suggest_fixes(self, wid: str, problem: str) -> dict:
        return self._req("POST", "/llm/suggest-fixes", {"workflow_id": wid, "problem": problem}).json()

    def validation_run(self, wid: str, prompt_version: str, n: int) -> dict:
        return self._req("POST", "/validation/runs",
                         {"workflow_id": wid, "prompt_version": prompt_version, "n": n}).json()
