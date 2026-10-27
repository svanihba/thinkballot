"""One place for all AI calls (OpenRouter), with timeouts, retries and a log line per request.

With TB_AI_PROVIDER=stub, no network call is made; a fixed stand-in replies instead, so the services and
tests can run offline. The stub is never used in production.
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import requests

from . import config

log = logging.getLogger("thinkballot.ai")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# requests' timeout limits each read, not the whole reply, so a slow trickle can run far past it.
# Each request runs on this pool and we stop waiting at the timeout; a late reply is discarded.
_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ai")
MIN_ATTEMPT_SECONDS = 5  # don't start an attempt with less time than this left


class AIError(Exception):
    """The model could not be reached or did not return usable JSON."""


def chat_json(model, system, user, stub=None, deadline=None):
    """Send one chat request and return the reply parsed as a JSON object.

    `stub` is a function(user) -> dict used when the provider is "stub".
    `deadline` (time.monotonic() value): no attempt starts or runs past it.
    """
    if config.AI_PROVIDER == "stub":
        if stub is None:
            raise AIError("no stub reply available")
        log.info("ai stub model=%s", model)
        return stub(user)
    if not config.OPENROUTER_API_KEY:
        raise AIError("OPENROUTER_API_KEY is not set")

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": "Bearer " + config.OPENROUTER_API_KEY, "X-Title": "ThinkBallot"}
    last_error = "no attempt"
    for attempt in range(config.AI_RETRIES + 1):
        started = time.monotonic()
        timeout = config.AI_TIMEOUT_SECONDS
        if deadline is not None:
            timeout = min(timeout, deadline - started)
            if timeout < MIN_ATTEMPT_SECONDS:
                log.info("ai model=%s attempt=%d skipped: out of time", model, attempt + 1)
                last_error = "out of time"
                break
        try:
            resp = _post(payload, headers, timeout)
            ms = (time.monotonic() - started) * 1000
            log.info("ai model=%s attempt=%d status=%s %.0f ms", model, attempt + 1, resp.status_code, ms)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return parse_json_object(content)
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code not in (408, 429, 500, 502, 503, 504):
                break  # not worth retrying
        except (requests.RequestException, FutureTimeout, KeyError, IndexError, ValueError) as exc:
            log.info("ai model=%s attempt=%d error=%s", model, attempt + 1, type(exc).__name__)
            last_error = type(exc).__name__
        pause = min(2 ** attempt, 8)
        if deadline is not None:
            pause = min(pause, max(deadline - time.monotonic(), 0))
        time.sleep(pause)
    raise AIError(last_error)


def _post(payload, headers, timeout):
    """POST to OpenRouter, giving up after `timeout` seconds in total (raises FutureTimeout)."""
    future = _pool.submit(requests.post, OPENROUTER_URL, json=payload, headers=headers, timeout=timeout)
    return future.result(timeout=timeout)


def parse_json_object(content):
    """Models sometimes wrap JSON in ``` fences or add a sentence; take the outermost {...}."""
    if not content:
        raise ValueError("empty reply")
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in reply")
    obj = json.loads(match.group(0))
    if not isinstance(obj, dict):
        raise ValueError("reply is not a JSON object")
    return obj
