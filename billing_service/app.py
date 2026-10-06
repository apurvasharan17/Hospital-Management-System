"""
billing_service/app.py
----------------------
Billing Service — the third participant in the Saga.

Responsibilities:
- create a bill (Saga ACTION) and cancel a bill (Saga COMPENSATION).
- a DEMO-ONLY "fail switch": POST /admin/fail-mode/on makes create-bill return
500 so you can trigger (a) Saga compensation and (b) the circuit breaker on
the caller. Turn it off with /admin/fail-mode/off.

Owner: Arpita (Resilience / Transactions).
Port: 5004
Run: python billing_service/app.py
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request

from billing_service.db import get_connection, init_db
from common.config import BILLING_PORT, HOST, public_url
from common.registry_client import register_forever


SERVICE_NAME = "billing-service"

app = Flask(__name__)

STATE = {"fail_mode": False}


@app.get("/health")
def health():
    return jsonify(
        status="up",
        service=SERVICE_NAME,
        fail_mode=STATE["fail_mode"]
    )


@app.post("/admin/fail-mode/on")
def fail_on():
    STATE["fail_mode"] = True
    return jsonify(message="fail mode ON — create-bill will now fail")


@app.post("/admin/fail-mode/off")
def fail_off():
    STATE["fail_mode"] = False
    return jsonify(message="fail mode OFF — create-bill works normally")


@app.post("/api/v1/bills")
def create_bill():
    if STATE["fail_mode"]:
        return jsonify(
            error="billing system unavailable (simulated)"
        ), 500

    data = request.get_json(silent=True) or {}

    appointment_id = data.get("appointment_id")
    amount = data.get("amount", 500.0)

    if appointment_id is None:
        return jsonify(error="'appointment_id' is required"), 400

    conn = get_connection()

    cur = conn.execute(
        "INSERT INTO bills (appointment_id, amount, status) VALUES (?,?,?)",
        (appointment_id, amount, "CREATED"),
    )

    conn.commit()

    bill_id = cur.lastrowid

    conn.close()

    return jsonify(
        id=bill_id,
        appointment_id=appointment_id,
        amount=amount,
        status="CREATED",
        message="bill created"
    ), 201


@app.get("/api/v1/bills/<int:bill_id>")
def get_bill(bill_id):
    conn = get_connection()

    row = conn.execute(
        "SELECT * FROM bills WHERE id=?",
        (bill_id,)
    ).fetchone()

    conn.close()

    if row is None:
        return jsonify(error="bill not found"), 404

    return jsonify({k: row[k] for k in row.keys()})


@app.post("/api/v1/bills/<int:bill_id>/cancel")
def cancel_bill(bill_id):
    """Compensation for create_bill: mark the bill CANCELLED."""

    conn = get_connection()

    row = conn.execute(
        "SELECT id FROM bills WHERE id=?",
        (bill_id,)
    ).fetchone()

    if row is None:
        conn.close()
        return jsonify(error="bill not found"), 404

    conn.execute(
        "UPDATE bills SET status='CANCELLED' WHERE id=?",
        (bill_id,)
    )

    conn.commit()
    conn.close()

    return jsonify(
        message="bill cancelled",
        bill_id=bill_id
    )


if __name__ == "__main__":
    init_db()
    register_forever(SERVICE_NAME, public_url(BILLING_PORT))

    print(f"Billing Service on http://{HOST}:{BILLING_PORT}")

    app.run(
        host=HOST,
        port=BILLING_PORT
    )