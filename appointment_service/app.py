"""
appointment_service/app.py
--------------------------
Appointment Service - the "third service" that COMMUNICATES with the others.
It is also where the booking Saga is orchestrated.

The booking flow (POST /api/v1/appointments) is a Saga across 3 services:
  1. verify patient exists        -> Patient Service   (read-only check)
  2. create appointment (PENDING) -> local DB
  3. reserve doctor slot          -> Doctor Service    (compensate: release)
  4. create bill                  -> Billing Service   (compensate: cancel)
  5. confirm appointment          -> local DB (status = CONFIRMED)

If step 3 or 4 fails, the Saga compensates in reverse and the appointment is
marked CANCELLED. All outbound calls go through the resilient client, so a dead
Doctor/Billing service trips a circuit breaker instead of hanging.

Response codes for a booking:
  201  CONFIRMED
  200  replay of an earlier request with the same idempotency_key
  400  bad input
  404  patient does not exist
  409  CANCELLED for a business reason (e.g. doctor has no free slots)
  503  CANCELLED / not started because a service was down or its breaker open

Owner: Communication + Service Discovery, using the shared saga + breaker.
Port: 5003
Run:  python appointment_service/app.py
"""
import os
import sqlite3
import sys
from contextlib import closing
from datetime import date as _date

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request

from appointment_service.db import get_connection, init_db
from common.config import APPOINTMENT_PORT, HOST, public_url
from common.http_client import breaker_status, call
from common.registry_client import register_forever
from common.saga import SagaOrchestrator

SERVICE_NAME = "appointment-service"
CONSULT_FEE = 500.0
app = Flask(__name__)


def row_to_dict(row):
    return {k: row[k] for k in row.keys()}


def fetch_appointment(column, value):
    """Look up one appointment by `id` or `idempotency_key`."""
    with closing(get_connection()) as conn:
        return conn.execute(
            f"SELECT * FROM appointments WHERE {column} = ?", (value,)
        ).fetchone()


def validate_booking(data):
    """Return an error message for a bad booking request, or None if it's fine."""
    for field in ("patient_id", "doctor_id", "date"):
        if field not in data:
            return f"'{field}' is required"
    for field in ("patient_id", "doctor_id"):
        value = data[field]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return f"'{field}' must be a positive integer"
    try:
        _date.fromisoformat(data["date"])
    except (TypeError, ValueError):
        return "'date' must be in YYYY-MM-DD format"
    return None


def replay(row):
    """Answer a retried request with the appointment it already created."""
    return jsonify(message="already processed (idempotent replay)",
                   **row_to_dict(row)), 200


@app.get("/health")
def health():
    # Surfacing breaker state here is handy for the circuit-breaker demo.
    return jsonify(status="up", service=SERVICE_NAME, breakers=breaker_status())


# ---- simple reads ----------------------------------------------------------
@app.get("/api/v1/appointments")
def list_appointments():
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM appointments").fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.get("/api/v1/appointments/<int:appointment_id>")
def get_appointment(appointment_id):
    row = fetch_appointment("id", appointment_id)
    if row is None:
        return jsonify(error="appointment not found"), 404
    return jsonify(row_to_dict(row))


# ---- the Saga: book an appointment -----------------------------------------
@app.post("/api/v1/appointments")
def book_appointment():
    data = request.get_json(silent=True) or {}
    error = validate_booking(data)
    if error:
        return jsonify(error=error), 400

    patient_id = data["patient_id"]
    doctor_id = data["doctor_id"]
    date = data["date"]
    reason = data.get("reason", "General consultation")
    # Optional. A client that retries with the same key gets the original
    # result back instead of a second booking. Use a new key to book again.
    idempotency_key = data.get("idempotency_key")

    if idempotency_key is not None:
        existing = fetch_appointment("idempotency_key", idempotency_key)
        if existing is not None:
            return replay(existing)

    # STEP 1 (pre-check): does the patient exist? This is inter-service
    # communication + circuit breaker. A `None` means the call failed or the
    # breaker is open -> we stop before creating anything.
    patient_resp = call("patient-service", "GET",
                        f"/api/v1/patients/{patient_id}")
    if patient_resp is None:
        return jsonify(error="patient service unavailable, try again later"), 503
    if patient_resp.status_code == 404:
        return jsonify(error="patient does not exist"), 404
    if patient_resp.status_code != 200:
        return jsonify(error=f"patient check failed: HTTP {patient_resp.status_code}"), 502

    # STEP 2: create the appointment locally in PENDING state.
    try:
        with closing(get_connection()) as conn:
            cur = conn.execute(
                "INSERT INTO appointments"
                " (patient_id, doctor_id, date, reason, status, idempotency_key)"
                " VALUES (?,?,?,?, 'PENDING', ?)",
                (patient_id, doctor_id, date, reason, idempotency_key),
            )
            conn.commit()
            appointment_id = cur.lastrowid
    except sqlite3.IntegrityError:
        # Two requests with the same key arrived together; the other one won.
        return replay(fetch_appointment("idempotency_key", idempotency_key))

    # Shared between the steps below.
    state = {
        "bill_id": None,
        "unavailable": False,           # a service was down / breaker open
        "compensation_failures": [],    # undo steps that did NOT go through
    }

    # Build the Saga steps (actions + compensations).
    saga = SagaOrchestrator("book-appointment")

    # --- action + compensation for the doctor slot ---
    def reserve_slot():
        resp = call("doctor-service", "POST",
                    f"/api/v1/doctors/{doctor_id}/reserve")
        if resp is None:
            state["unavailable"] = True
            raise RuntimeError("doctor service unavailable (breaker open?)")
        if resp.status_code != 200:
            raise RuntimeError(f"could not reserve slot: HTTP {resp.status_code}")
        return resp.json()

    def release_slot():
        resp = call("doctor-service", "POST",
                    f"/api/v1/doctors/{doctor_id}/release")
        # Raise instead of failing silently: the Saga logs it, and the
        # caller sees that a doctor slot is still held and needs a fix.
        if resp is None or resp.status_code != 200:
            state["compensation_failures"].append(
                f"release slot for doctor {doctor_id}")
            raise RuntimeError("could not release doctor slot")

    # --- action + compensation for the bill ---
    def create_bill():
        resp = call("billing-service", "POST", "/api/v1/bills",
                    json={"appointment_id": appointment_id, "amount": CONSULT_FEE})
        if resp is None:
            state["unavailable"] = True
            raise RuntimeError("billing service unavailable (breaker open?)")
        if resp.status_code != 201:
            raise RuntimeError(f"billing failed: HTTP {resp.status_code}")
        body = resp.json()
        state["bill_id"] = body["id"]
        return body

    def cancel_bill():
        if state["bill_id"] is None:
            return
        resp = call("billing-service", "POST",
                    f"/api/v1/bills/{state['bill_id']}/cancel")
        if resp is None or resp.status_code != 200:
            state["compensation_failures"].append(
                f"cancel bill {state['bill_id']}")
            raise RuntimeError("could not cancel bill")

    saga.add_step("reserve-doctor-slot", reserve_slot, release_slot)
    saga.add_step("create-bill", create_bill, cancel_bill)

    result = saga.execute()

    # STEP 5: finalise the appointment based on the Saga outcome.
    with closing(get_connection()) as conn:
        if result.ok:
            conn.execute(
                "UPDATE appointments SET status='CONFIRMED', bill_id=? WHERE id=?",
                (state["bill_id"], appointment_id),
            )
            conn.commit()
            return jsonify(
                message="appointment confirmed",
                appointment_id=appointment_id,
                bill_id=state["bill_id"],
                status="CONFIRMED",
            ), 201

        conn.execute(
            "UPDATE appointments SET status='CANCELLED' WHERE id=?",
            (appointment_id,),
        )
        conn.commit()

    body = dict(
        message="appointment cancelled - Saga rolled back",
        appointment_id=appointment_id,
        failed_step=result.failed_step,
        reason=result.error,
        status="CANCELLED",
    )
    if state["compensation_failures"]:
        body["compensation_failures"] = state["compensation_failures"]
    return jsonify(body), 503 if state["unavailable"] else 409


if __name__ == "__main__":
    init_db()
    register_forever(SERVICE_NAME, public_url(APPOINTMENT_PORT))
    print(f"Appointment Service on http://{HOST}:{APPOINTMENT_PORT}")
    app.run(host=HOST, port=APPOINTMENT_PORT)
