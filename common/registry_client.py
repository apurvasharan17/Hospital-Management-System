"""
common/registry_client.py
-------------------------
Service-discovery CLIENT. Every service uses this to (a) announce itself to the
registry when it boots and (b) look up where another service lives, by name,
instead of hard-coding URLs.

Owner: Communication / Service Discovery.

Pairs with: service_registry/app.py (the registry SERVER).
"""
import threading
import time

import requests

from common.config import REGISTRY_URL

# Short timeout so a slow/missing registry never freezes a service.
_TIMEOUT = 3

# Tiny in-process cache so we don't hit the registry on every single call.
_cache = {}
_cache_ttl = 10  # seconds


def register(name, url):
    """Announce `name` -> `url` to the registry. Never crashes the caller."""
    try:
        resp = requests.post(
            f"{REGISTRY_URL}/register",
            json={"name": name, "url": url},
            timeout=_TIMEOUT,
        )
        if resp.status_code != 201:
            print(f"[discovery] registry rejected '{name}': HTTP {resp.status_code}")
            return False
        print(f"[discovery] registered '{name}' at {url}")
        return True
    except requests.RequestException as exc:
        # A missing registry must not stop a service from starting.
        print(f"[discovery] could not register '{name}': {exc}")
        return False


def register_forever(name, url, interval=15):
    """
    Re-register every `interval` seconds in a background thread. This is a
    lightweight heartbeat: if the registry restarts, services re-appear on
    their own, and if a service dies, the registry notices the missing
    heartbeats and drops it.
    """

    def _loop():
        while True:
            register(name, url)
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def discover(name):
    """
    Return the base URL for a service by name, or None if it is unknown.
    Uses a short TTL cache to reduce chatter.
    """
    now = time.time()
    cached = _cache.get(name)
    if cached and now - cached[1] < _cache_ttl:
        return cached[0]

    try:
        resp = requests.get(f"{REGISTRY_URL}/services/{name}", timeout=_TIMEOUT)
        if resp.status_code == 200:
            url = resp.json()["url"]
            _cache[name] = (url, now)
            return url
        if resp.status_code == 404:
            # The registry says it's gone (e.g. heartbeats stopped). Trust that
            # over our cache, otherwise we'd keep calling a dead process.
            _cache.pop(name, None)
            return None
    except requests.RequestException as exc:
        print(f"[discovery] lookup for '{name}' failed: {exc}")

    # Registry unreachable: fall back to a stale cache entry - better than nothing.
    return cached[0] if cached else None
