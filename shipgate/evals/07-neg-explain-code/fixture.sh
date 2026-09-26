#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
cat > http_client.py <<'PY'
import random
import socket
import time
import urllib.error
import urllib.request

MAX_RETRIES = 3
BASE_DELAY = 0.5


def _should_retry(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return 500 <= exc.code < 600
    return isinstance(exc, (socket.timeout, TimeoutError, urllib.error.URLError))


def get(url, timeout=5):
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            if attempt == MAX_RETRIES or not _should_retry(exc):
                raise
            time.sleep(random.uniform(0, BASE_DELAY * 2 ** attempt))
PY
c 2026-09-10 "feat: http client with retries"
