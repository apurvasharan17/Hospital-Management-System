"""
api_gateway/app.py
------------------
The API Gateway — the single front door for all clients.

Clients only ever talk to the gateway (port 8080). The gateway looks up the
target service by NAME in the registry (service discovery) and forwards the
request, preserving the path (so /api/v1/... and /api/v2/... both work).

Routing rules (by the first path segment after /api/<version>/):
    /api/<v>/patients...      -> patient-service
    /api/<v>/doctors...       -> doctor-service
    /api/<v>/appointments...  -> appointment-service
    /api/<v>/bills...         -> billing-service

Owner: Apurva (Integration / Gateway).
Port: 8080
Run:  python api_gateway/app.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from flask import Flask, Response, jsonify, request

from common.config import GATEWAY_PORT, HOST
from common.registry_client import discover

app = Flask(__name__)
_TIMEOUT = 6

# Map the resource name in the URL to the service that owns it.
RESOURCE_TO_SERVICE = {
    "patients": "patient-service",
    "doctors": "doctor-service",
    "appointments": "appointment-service",
    "bills": "billing-service",
}


@app.get("/health")
def health():
    return jsonify(status="up", service="api-gateway")


@app.get("/")
def index():
    return jsonify(
        message="Hospital Management System — API Gateway",
        try_this=[
            "GET  /api/v1/patients",
            "GET  /api/v1/doctors",
            "POST /api/v1/appointments",
            "GET  /api/v2/patients",
        ],
    )


# One catch-all route that forwards any /api/<version>/<resource>/... request.
@app.route(
    "/api/<version>/<resource>",
    methods=["GET", "POST", "PUT", "DELETE"],
)
@app.route(
    "/api/<version>/<resource>/<path:rest>",
    methods=["GET", "POST", "PUT", "DELETE"],
)
def gateway(version, resource, rest=""):
    service_name = RESOURCE_TO_SERVICE.get(resource)
    if service_name is None:
        return jsonify(error=f"unknown resource '{resource}'"), 404

    base = discover(service_name)
    if base is None:
        return jsonify(error=f"{service_name} not registered / unavailable"), 503

    # Rebuild the downstream path exactly as the client sent it.
    downstream_path = f"/api/{version}/{resource}"
    if rest:
        downstream_path += f"/{rest}"
    url = f"{base}{downstream_path}"

    try:
        resp = requests.request(
            request.method,
            url,
            json=request.get_json(silent=True),
            params=request.args,
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        return jsonify(error=f"gateway could not reach {service_name}: {exc}"), 502

    # Pass the downstream response straight back to the client.
    return Response(
        resp.content,
        status=resp.status_code,
        content_type=resp.headers.get("Content-Type", "application/json"),
    )


if __name__ == "__main__":
    print(f"API Gateway on http://{HOST}:{GATEWAY_PORT}")
    app.run(host=HOST, port=GATEWAY_PORT)