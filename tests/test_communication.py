"""
tests/test_communication.py
------------------
Unit tests for the two Communication components: the Service Registry and the
Appointment Service's booking Saga.

These run WITHOUT starting any servers. Flask's test_client() drives the
registry directly, and the calls into the Patient / Doctor / Billing services
are replaced with fakes, so the whole booking Saga can be tested on its own.

Run from the repo root:  pytest -q
"""
import os
import sys
import time

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===================== Service Registry =====================================
@pytest.fixture
def registry():
    from service_registry import app as reg

    reg.SERVICES.clear()
    return reg


def test_register_then_discover(registry):
    client = registry.app.test_client()
    resp = client.post("/register",
                       json={"name": "doctor-service", "url": "http://x:5002"})
    assert resp.status_code == 201

    resp = client.get("/services/doctor-service")
    assert resp.status_code == 200
    assert resp.get_json()["url"] == "http://x:5002"


def test_register_requires_name_and_url(registry):
    client = registry.app.test_client()
    assert client.post("/register", json={"name": "x"}).status_code == 400
    assert client.post("/register", json={}).status_code == 400


def test_unknown_service_is_404(registry):
    client = registry.app.test_client()
    assert client.get("/services/nope").status_code == 404


def test_expired_service_is_evicted(registry, monkeypatch):
    """A service that stops sending heartbeats is dropped from the registry."""
    # A short TTL keeps the test quick. The sleep below clears it with a wide
    # margin so a slow or loaded machine (or a coarse Windows timer) can't
    # make this fail intermittently.
    monkeypatch.setattr(registry, "SERVICE_TTL", 0.3)
    client = registry.app.test_client()
    client.post("/register", json={"name": "doctor-service", "url": "http://x"})

    assert client.get("/services/doctor-service").status_code == 200
    time.sleep(0.6)
    assert client.get("/services/doctor-service").status_code == 404
    assert client.get("/services").get_json() == {}


def test_deregister(registry):
    client = registry.app.test_client()
    client.post("/register", json={"name": "a", "url": "http://a"})
    assert client.delete("/services/a").status_code == 200
    assert client.get("/services/a").status_code == 404


# ===================== Appointment Service / Saga ===========================
class FakeResponse:
    """Stands in for a requests.Response."""

    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


@pytest.fixture
def appt(tmp_path, monkeypatch):
    """Appointment service wired to a temp DB, with outbound calls faked."""
    # The outbound CALLS are faked below, but importing the service still needs
    # the resilience modules to exist. Until the Resilience developer has
    # pushed them, skip these with a clear message instead of 15 import errors.
    pytest.importorskip(
        "common.http_client",
        reason="needs common/http_client.py + common/saga.py (Resilience). "
               "The registry tests above run regardless.",
    )
    pytest.importorskip("common.saga")

    from appointment_service import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "appointment.db"))
    db.init_db()

    from appointment_service import app as appt_app

    # calls[i] = (service, method, path) so tests can assert what was called.
    calls = []
    # Default: every downstream service is healthy.
    responses = {
        "patient-service": FakeResponse(200, {"id": 1, "name": "Ravi"}),
        "doctor-service": FakeResponse(200, {"message": "slot reserved"}),
        "billing-service": FakeResponse(201, {"id": 77, "status": "CREATED"}),
    }

    def fake_call(service_name, method, path, json=None, fallback=None):
        calls.append((service_name, method, path))
        value = responses[service_name]
        # A list lets a test give different answers to successive calls.
        if isinstance(value, list):
            return value.pop(0) if value else FakeResponse(500)
        return value

    monkeypatch.setattr(appt_app, "call", fake_call)
    appt_app.app.config["TESTING"] = True

    class Harness:
        def __init__(self):
            self.client = appt_app.app.test_client()
            self.calls = calls
            self.responses = responses

        def book(self, **overrides):
            body = {"patient_id": 1, "doctor_id": 1, "date": "2026-09-15"}
            body.update(overrides)
            return self.client.post("/api/v1/appointments", json=body)

    return Harness()


def test_booking_happy_path(appt):
    resp = appt.book()
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "CONFIRMED"
    assert body["bill_id"] == 77

    # It really did talk to all three services - this is the "communication
    # between 3+ services" rubric item.
    services = [c[0] for c in appt.calls]
    assert services == ["patient-service", "doctor-service", "billing-service"]


@pytest.mark.parametrize("payload, expected_error", [
    ({"doctor_id": 1, "date": "2026-09-15"}, "patient_id"),
    ({"patient_id": 1, "date": "2026-09-15"}, "doctor_id"),
    ({"patient_id": 1, "doctor_id": 1}, "date"),
])
def test_missing_fields_are_400(appt, payload, expected_error):
    resp = appt.client.post("/api/v1/appointments", json=payload)
    assert resp.status_code == 400
    assert expected_error in resp.get_json()["error"]


def test_bad_types_are_400(appt):
    assert appt.book(patient_id="1").status_code == 400
    assert appt.book(doctor_id=-5).status_code == 400
    assert appt.book(date="15/09/2026").status_code == 400


def test_unknown_patient_is_404(appt):
    appt.responses["patient-service"] = FakeResponse(404)
    resp = appt.book()
    assert resp.status_code == 404
    # Nothing else should have been called - we stop at the pre-check.
    assert [c[0] for c in appt.calls] == ["patient-service"]


def test_patient_service_down_is_503(appt):
    appt.responses["patient-service"] = None  # breaker open / call failed
    resp = appt.book()
    assert resp.status_code == 503
    assert "unavailable" in resp.get_json()["error"]


def test_no_slots_rolls_back_with_409(appt):
    """A business failure (doctor full) -> 409, appointment CANCELLED."""
    appt.responses["doctor-service"] = FakeResponse(409, {"error": "no slots"})
    resp = appt.book()
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["status"] == "CANCELLED"
    assert body["failed_step"] == "reserve-doctor-slot"
    # Billing was never reached, so there is nothing to cancel.
    assert "billing-service" not in [c[0] for c in appt.calls]


def test_billing_failure_compensates_the_doctor_slot(appt):
    """
    The key Saga test: billing fails AFTER the slot was reserved, so the
    reserve must be compensated by a release call.
    """
    appt.responses["billing-service"] = FakeResponse(500)
    appt.responses["doctor-service"] = [
        FakeResponse(200, {"message": "slot reserved"}),  # reserve
        FakeResponse(200, {"message": "slot released"}),  # release (compensation)
    ]
    resp = appt.book()
    assert resp.status_code == 409
    assert resp.get_json()["status"] == "CANCELLED"

    # The compensation ran: a release was called for the same doctor.
    assert ("doctor-service", "POST", "/api/v1/doctors/1/release") in appt.calls


def test_billing_down_is_503_and_compensates(appt):
    appt.responses["billing-service"] = None  # service down / breaker open
    appt.responses["doctor-service"] = [
        FakeResponse(200, {"message": "slot reserved"}),
        FakeResponse(200, {"message": "slot released"}),
    ]
    resp = appt.book()
    assert resp.status_code == 503  # down, not a business conflict
    assert ("doctor-service", "POST", "/api/v1/doctors/1/release") in appt.calls


def test_failed_compensation_is_reported(appt):
    """
    If the release ALSO fails, the response says so instead of hiding it -
    a slot is stuck and somebody has to know.
    """
    appt.responses["billing-service"] = FakeResponse(500)
    appt.responses["doctor-service"] = [
        FakeResponse(200, {"message": "slot reserved"}),
        None,  # release fails too
    ]
    resp = appt.book()
    body = resp.get_json()
    assert body["status"] == "CANCELLED"
    assert "compensation_failures" in body
    assert "release slot for doctor 1" in body["compensation_failures"]


def test_idempotency_key_prevents_double_booking(appt):
    first = appt.book(idempotency_key="abc")
    assert first.status_code == 201
    appointment_id = first.get_json()["appointment_id"]

    second = appt.book(idempotency_key="abc")
    assert second.status_code == 200  # replay, not a new booking
    assert second.get_json()["id"] == appointment_id

    # Only one appointment exists.
    rows = appt.client.get("/api/v1/appointments").get_json()
    assert len(rows) == 1

    # And - just as important - the replay must not have re-run the Saga.
    # If it did, it would reserve a SECOND doctor slot and create a second
    # bill, leaking both. There are two defences: the up-front key lookup,
    # and the UNIQUE constraint on the column if two requests race.
    assert [c[0] for c in appt.calls].count("doctor-service") == 1
    assert [c[0] for c in appt.calls].count("billing-service") == 1
    # The up-front lookup means a replay costs no downstream calls at all.
    assert [c[0] for c in appt.calls].count("patient-service") == 1


def test_different_keys_create_separate_bookings(appt):
    assert appt.book(idempotency_key="k1").status_code == 201
    assert appt.book(idempotency_key="k2").status_code == 201
    assert len(appt.client.get("/api/v1/appointments").get_json()) == 2


def test_get_appointment(appt):
    appointment_id = appt.book().get_json()["appointment_id"]
    resp = appt.client.get(f"/api/v1/appointments/{appointment_id}")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "CONFIRMED"
    assert appt.client.get("/api/v1/appointments/999").status_code == 404


def test_health_exposes_breaker_state(appt):
    body = appt.client.get("/health").get_json()
    assert body["status"] == "up"
    assert body["service"] == "appointment-service"
    assert "breakers" in body
