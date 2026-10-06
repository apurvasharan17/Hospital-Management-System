import requests

from common.registry_client import discover
from common.circuit_breaker import CircuitBreaker


# One circuit breaker per service
_breakers = {}


def _get_breaker(service_name):
    if service_name not in _breakers:
        _breakers[service_name] = CircuitBreaker(
            name=service_name,
            failure_threshold=3,
            recovery_timeout=10,
        )

    return _breakers[service_name]


def _make_request(url, method, **kwargs):
    response = requests.request(
        method=method,
        url=url,
        timeout=kwargs.pop("timeout", 5),
        **kwargs,
    )

    response.raise_for_status()

    return response


def call(service_name, method, path, **kwargs):
    """
    Make an HTTP request to another microservice.

    service_name: registered service name, e.g. "billing-service"
    method: HTTP method, e.g. "GET", "POST"
    path: endpoint path, e.g. "/api/v1/bills"
    """

    # 1. Find the service address using service discovery
    base_url = discover(service_name)

    if not base_url:
        raise RuntimeError(f"Service '{service_name}' not found")

    # 2. Build the complete URL
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    # 3. Get this service's circuit breaker
    breaker = _get_breaker(service_name)

    # 4. Make the HTTP request through the circuit breaker
    return breaker.call(
        _make_request,
        url,
        method,
        fallback=None,
        **kwargs,
    )