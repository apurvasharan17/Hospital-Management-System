"""
appointment_service/db.py
-------------------------
Owns the APPOINTMENT database (appointment.db). Stores appointments and their
lifecycle status (PENDING -> CONFIRMED, or CANCELLED if the Saga rolls back).

Owner: Communication Developer.
"""
import os
import sqlite3
from contextlib import closing

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "appointment.db"
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    # `closing` guarantees the handle is released even if a statement raises.
    # On Windows an open SQLite handle blocks the file from being deleted,
    # which would break pytest's temp-directory cleanup.
    with closing(get_connection()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS appointments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id      INTEGER NOT NULL,
                doctor_id       INTEGER NOT NULL,
                date            TEXT    NOT NULL,
                reason          TEXT,
                status          TEXT    NOT NULL DEFAULT 'PENDING',
                bill_id         INTEGER,
                idempotency_key TEXT    UNIQUE
            )
            """
        )
        # An appointment.db created by an older version of this file won't have
        # the idempotency_key column yet - add it instead of forcing a delete.
        columns = [
            row["name"] for row in conn.execute("PRAGMA table_info(appointments)")
        ]
        if "idempotency_key" not in columns:
            conn.execute(
                "ALTER TABLE appointments ADD COLUMN idempotency_key TEXT"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_idem "
                "ON appointments(idempotency_key)"
            )
        conn.commit()
