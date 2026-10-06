"""
service_registry/app.py
-----------------------
The Service Discovery SERVER (a.k.a. the registry).

Every other service POSTs its {name, url} here on startup, and then again
every 15 seconds as a heartbeat. Anyone who needs to call a service asks
GET /services/<name> and gets back its URL. This is what lets us avoid
hard-coding "http://127.0.0.1:5002" everywhere.

A service that misses its heartbeats for SERVICE_TTL seconds is treated as
gone and removed, so callers get a clean "not found" instead of the URL of a
dead process.

Owner: Communication / Service Discovery.
Port: 5000
Database: none needed - an in-memory dict is fine for a discovery registry.
Run:  python service_registry/app.py
"""
import os
import sys
import threading
import time

# Make the repo root importable so `from common...` works no matter where we
# launch the script from.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request

from common.config import HOST, REGISTRY_PORT

app = Flask(__name__)

# register_forever() re-registers every 15s, so 45s = three missed heartbeats.
SERVICE_TTL = 45

# name -> {"url": ..., "last_seen": epoch_seconds}
SERVICES = {}
# Flask serves requests on several threads; guard the dict.
_lock = threading.Lock()


def _evict_expired():
    """Drop services whose last heartbeat is older than SERVICE_TTL."""
    now = time.time()
    with _lock:
        expired = [
            name for name, info in SERVICES.items()
            if now - info["last_seen"] >= SERVICE_TTL
        ]
        for name in expired:
            del SERVICES[name]
            print(f"[registry] {name} expired (no heartbeat for {SERVICE_TTL}s)")


@app.get("/health")
def health():
    return jsonify(status="up", service="service-registry")


@app.post("/register")
def register():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    url = body.get("url")
    if not name or not url:
        return jsonify(error="name and url are required"), 400
    with _lock:
        SERVICES[name] = {"url": url, "last_seen": time.time()}
    print(f"[registry] {name} -> {url}")
    return jsonify(message="registered", name=name, url=url), 201


@app.get("/services")
def list_services():
    """Return every live service (handy for demos and debugging)."""
    _evict_expired()
    with _lock:
        return jsonify({n: info["url"] for n, info in SERVICES.items()})


@app.get("/services/<name>")
def get_service(name):
    _evict_expired()
    with _lock:
        info = SERVICES.get(name)
    if not info:
        return jsonify(error=f"service '{name}' not found"), 404
    return jsonify(name=name, url=info["url"])


@app.delete("/services/<name>")
def deregister(name):
    with _lock:
        SERVICES.pop(name, None)
    return jsonify(message="deregistered", name=name)


if __name__ == "__main__":
    print(f"Service Registry listening on http://{HOST}:{REGISTRY_PORT}")
    app.run(host=HOST, port=REGISTRY_PORT)
