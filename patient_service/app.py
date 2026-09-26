"""
patient_service/app.py
----------------------
Microservice 1 — Patient Service (the "core" service).

Responsibilities:
- Full CRUD over patients (GET/POST/PUT/DELETE) -> demonstrates REST design.
- Two API versions (v1 and v2) -> demonstrates API versioning.
- Registers itself with the service registry -> demonstrates discovery.
- Owns patient.db and never touches another service's DB -> data isolation.

Owner: Ashish (Microservice 1).
Port: 5001
Run: python patient_service/app.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request

from common.config import HOST, PATIENT_PORT, public_url
from common.registry_client import register_forever
from patient_service.db import get_connection, init_db

SERVICE_NAME = "patient-service"
app = Flask(__name__)


# ---- helpers ---------------------------------------------------------------
def row_to_dict(row):
    return {k: row[k] for k in row.keys()}


def fetch_patient(patient_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM patients WHERE id = ?", (patient_id,)
    ).fetchone()
    conn.close()
    return row


# ---- health (used by the gateway and by graders) ---------------------------
@app.get("/health")
def health():
    return jsonify(status="up", service=SERVICE_NAME)


# ======================= API v1 ============================================
@app.get("/api/v1/patients")
def v1_list():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM patients").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])


@app.get("/api/v1/patients/<int:patient_id>")
def v1_get(patient_id):
    row = fetch_patient(patient_id)
    if row is None:
        return jsonify(error="patient not found"), 404
    return jsonify(row_to_dict(row))


@app.post("/api/v1/patients")
def v1_create():
    data = request.get_json(silent=True) or {}
    for field in ("name", "age", "gender", "phone"):
        if field not in data:
            return jsonify(error=f"'{field}' is required"), 400

    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO patients (name, age, gender, phone) VALUES (?,?,?,?)",
        (data["name"], data["age"], data["gender"], data["phone"]),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return jsonify(id=new_id, message="patient created"), 201


@app.put("/api/v1/patients/<int:patient_id>")
def v1_update(patient_id):
    if fetch_patient(patient_id) is None:
        return jsonify(error="patient not found"), 404

    data = request.get_json(silent=True) or {}
    conn = get_connection()
    conn.execute(
        "UPDATE patients SET name=?, age=?, gender=?, phone=? WHERE id=?",
        (
            data.get("name"),
            data.get("age"),
            data.get("gender"),
            data.get("phone"),
            patient_id,
        ),
    )
    conn.commit()
    conn.close()
    return jsonify(message="patient updated")


@app.delete("/api/v1/patients/<int:patient_id>")
def v1_delete(patient_id):
    if fetch_patient(patient_id) is None:
        return jsonify(error="patient not found"), 404

    conn = get_connection()
    conn.execute("DELETE FROM patients WHERE id=?", (patient_id,))
    conn.commit()
    conn.close()
    return jsonify(message="patient deleted")


# ======================= API v2 ============================================
# v2 demonstrates a *real* versioning difference: the response is wrapped in a
# richer envelope and adds a derived "category" field. v1 stays unchanged so
# old clients keep working.
def _age_category(age):
    if age < 18:
        return "child"
    if age >= 60:
        return "senior"
    return "adult"


@app.get("/api/v2/patients")
def v2_list():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM patients").fetchall()
    conn.close()
    items = []
    for r in rows:
        d = row_to_dict(r)
        d["category"] = _age_category(d["age"])
        items.append(d)
    return jsonify(version="v2", count=len(items), data=items)


@app.get("/api/v2/patients/<int:patient_id>")
def v2_get(patient_id):
    row = fetch_patient(patient_id)
    if row is None:
        return jsonify(error="patient not found"), 404
    d = row_to_dict(row)
    d["category"] = _age_category(d["age"])
    return jsonify(version="v2", data=d)


if __name__ == "__main__":
    init_db()
    register_forever(SERVICE_NAME, public_url(PATIENT_PORT))
    print(f"Patient Service on http://{HOST}:{PATIENT_PORT}")
    app.run(host=HOST, port=PATIENT_PORT)
