"""
common/http_client.py
---------------------
The one place inter-service HTTP calls go through.

It combines:
- service discovery
- per-service circuit breakers

4xx responses are returned normally because they represent
business-level errors.

5xx responses and connection/transport errors are treated as
service failures and count toward the circuit breaker.
"""

import requests

from common.circuit_breaker import CircuitBreaker
from common.registry_client import discover


_TIMEOUT = 4

# One circuit breaker per downstream service.
_breakers = {}


class ServiceCallError(Exception):
    """Raised when a downstream service is unavailable or returns 5xx."""
    pass


def _breaker_for(service_name):
    """Return the circuit breaker for a service, creating it if needed."""
    if service_name not in _breakers:
        _breakers[service_name] = CircuitBreaker(
            name=service_name,
            failure_threshold=3,
            recovery_timeout=10,
        )

    return _breakers[service_name]


def breaker_status():
    """Return the status of every downstream circuit breaker."""
    return {
        name: breaker.status()
        for name, breaker in _breakers.items()
    }


def _raw_call(service_name, method, path, json=None):
    """
    Perform the actual network request.

    4xx = normal business response.
    5xx = service failure -> raise so the breaker counts it.
    Connection/timeout errors = naturally raise so the breaker counts them.
    """

    base_url = discover(service_name)

    if base_url is None:
        raise ServiceCallError(
            f"service '{service_name}' not found in registry"
        )

    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    response = requests.request(
        method=method,
        url=url,
        json=json,
        timeout=_TIMEOUT,
    )

    # 5xx means the downstream service itself failed.
    # Raise so CircuitBreaker records a failure.
    if response.status_code >= 500:
        raise ServiceCallError(
            f"{service_name} returned HTTP {response.status_code}"
        )

    # 4xx responses are returned normally.
    # They represent business/application errors such as:
    # 404 patient not found
    # 409 doctor has no available slot
    return response


def call(service_name, method, path, json=None, fallback=None):
    """
    Make a resilient HTTP request to another microservice.

    service_name:
        Registered service name, e.g. "billing-service"

    method:
        HTTP method, e.g. "GET" or "POST"

    path:
        Endpoint path, e.g. "/api/v1/bills"

    json:
        Optional JSON request body.

    fallback:
        Value returned when the circuit is OPEN or the request fails.
        Defaults to None.
    """

    breaker = _breaker_for(service_name)

    return breaker.call(
        _raw_call,
        service_name,
        method,
        path,
        json=json,
        fallback=fallback,
    )