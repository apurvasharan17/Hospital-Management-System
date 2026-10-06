import os
import sys

# Allow Python to find the common package from the project root
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from flask import Flask, jsonify, request

from doctor.db import get_connection, init_db

# These will be provided by the common folder of the team project
from common.config import DOCTOR_PORT, HOST, public_url
from common.registry_client import register_forever


SERVICE_NAME = "doctor-service"

app = Flask(__name__)


def row_to_dict(row):
    """Convert a database row into a normal Python dictionary."""
    return {key: row[key] for key in row.keys()}


def get_doctor(doctor_id):
    """Find one doctor using the doctor ID."""

    connection = get_connection()

    doctor = connection.execute(
        "SELECT * FROM doctors WHERE id = ?",
        (doctor_id,)
    ).fetchone()

    connection.close()

    return doctor


# ---------------------------------------------------------
# Health Check
# ---------------------------------------------------------

@app.get("/health")
def health():
    return jsonify(
        status="up",
        service=SERVICE_NAME
    )


# =========================================================
# API VERSION 1
# =========================================================

# Get all doctors
@app.get("/api/v1/doctors")
def get_doctors():

    connection = get_connection()

    doctors = connection.execute(
        "SELECT * FROM doctors"
    ).fetchall()

    connection.close()

    return jsonify([
        row_to_dict(doctor)
        for doctor in doctors
    ])


# Get one doctor
@app.get("/api/v1/doctors/<int:doctor_id>")
def get_one_doctor(doctor_id):

    doctor = get_doctor(doctor_id)

    if doctor is None:
        return jsonify(
            error="doctor not found"
        ), 404

    return jsonify(row_to_dict(doctor))


# Create a doctor
@app.post("/api/v1/doctors")
def create_doctor():

    data = request.get_json(silent=True) or {}

    # Required fields
    for field in ("name", "specialization"):
        if field not in data:
            return jsonify(
                error=f"'{field}' is required"
            ), 400

    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO doctors
        (name, specialization, phone, email, clinic_id, available_slots)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"],
            data["specialization"],
            data.get("phone"),
            data.get("email"),
            data.get("clinic_id"),
            data.get("available_slots", 5)
        )
    )

    connection.commit()

    doctor_id = cursor.lastrowid

    connection.close()

    return jsonify(
        id=doctor_id,
        message="doctor created"
    ), 201


# Update a doctor
@app.put("/api/v1/doctors/<int:doctor_id>")
def update_doctor(doctor_id):

    if get_doctor(doctor_id) is None:
        return jsonify(
            error="doctor not found"
        ), 404

    data = request.get_json(silent=True) or {}

    connection = get_connection()

    connection.execute(
        """
        UPDATE doctors
        SET name = ?,
            specialization = ?,
            phone = ?,
            email = ?,
            clinic_id = ?,
            available_slots = ?
        WHERE id = ?
        """,
        (
            data.get("name"),
            data.get("specialization"),
            data.get("phone"),
            data.get("email"),
            data.get("clinic_id"),
            data.get("available_slots"),
            doctor_id
        )
    )

    connection.commit()
    connection.close()

    return jsonify(
        message="doctor updated"
    )


# Delete a doctor
@app.delete("/api/v1/doctors/<int:doctor_id>")
def delete_doctor(doctor_id):

    if get_doctor(doctor_id) is None:
        return jsonify(
            error="doctor not found"
        ), 404

    connection = get_connection()

    connection.execute(
        "DELETE FROM doctors WHERE id = ?",
        (doctor_id,)
    )

    connection.commit()
    connection.close()

    return jsonify(
        message="doctor deleted"
    )


# =========================================================
# RESERVE DOCTOR SLOT
# =========================================================

@app.post("/api/v1/doctors/<int:doctor_id>/reserve")
def reserve_slot(doctor_id):

    connection = get_connection()

    doctor = connection.execute(
        """
        SELECT available_slots
        FROM doctors
        WHERE id = ?
        """,
        (doctor_id,)
    ).fetchone()

    # Doctor doesn't exist
    if doctor is None:
        connection.close()

        return jsonify(
            error="doctor not found"
        ), 404

    # No slots remaining
    if doctor["available_slots"] <= 0:
        connection.close()

        return jsonify(
            error="no slots available"
        ), 409

    # Reserve one slot
    connection.execute(
        """
        UPDATE doctors
        SET available_slots = available_slots - 1
        WHERE id = ?
        """,
        (doctor_id,)
    )

    connection.commit()

    remaining_slots = connection.execute(
        """
        SELECT available_slots
        FROM doctors
        WHERE id = ?
        """,
        (doctor_id,)
    ).fetchone()["available_slots"]

    connection.close()

    return jsonify(
        message="slot reserved",
        doctor_id=doctor_id,
        remaining_slots=remaining_slots
    ), 200


# =========================================================
# RELEASE DOCTOR SLOT
# =========================================================

@app.post("/api/v1/doctors/<int:doctor_id>/release")
def release_slot(doctor_id):

    connection = get_connection()

    doctor = connection.execute(
        "SELECT id FROM doctors WHERE id = ?",
        (doctor_id,)
    ).fetchone()

    if doctor is None:
        connection.close()

        return jsonify(
            error="doctor not found"
        ), 404

    # Give the reserved slot back
    connection.execute(
        """
        UPDATE doctors
        SET available_slots = available_slots + 1
        WHERE id = ?
        """,
        (doctor_id,)
    )

    connection.commit()
    connection.close()

    return jsonify(
        message="slot released",
        doctor_id=doctor_id
    ), 200


# =========================================================
# API VERSION 2
# =========================================================

@app.get("/api/v2/doctors")
def get_doctors_v2():

    connection = get_connection()

    doctors = connection.execute(
        "SELECT * FROM doctors"
    ).fetchall()

    connection.close()

    result = []

    for doctor in doctors:

        doctor_data = row_to_dict(doctor)

        # Extra information provided by API v2
        doctor_data["is_available"] = (
            doctor_data["available_slots"] > 0
        )

        result.append(doctor_data)

    return jsonify(
        version="v2",
        count=len(result),
        data=result
    )


@app.get("/api/v2/doctors/<int:doctor_id>")
def get_one_doctor_v2(doctor_id):

    doctor = get_doctor(doctor_id)

    if doctor is None:
        return jsonify(
            error="doctor not found"
        ), 404

    doctor_data = row_to_dict(doctor)

    doctor_data["is_available"] = (
        doctor_data["available_slots"] > 0
    )

    return jsonify(
        version="v2",
        data=doctor_data
    )



# START DOCTOR SERVICE


if __name__ == "__main__":

    # Create database if necessary
    init_db()

    # Register this service with the Service Registry
    register_forever(
        SERVICE_NAME,
        public_url(DOCTOR_PORT)
    )

    print(
        f"Doctor Service running on "
        f"http://{HOST}:{DOCTOR_PORT}"
    )

    app.run(
        host=HOST,
        port=DOCTOR_PORT
    )