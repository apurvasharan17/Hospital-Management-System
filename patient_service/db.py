"""
patient_service/db.py
---------------------
Owns the PATIENT database (patient.db). This is the only file allowed to touch
patient data — no other service may read this DB directly (data isolation).

Owner: Ashish (Microservice 1).
"""
import os
import sqlite3

# Keep the .db file next to this service's code so it is clearly "owned" here.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patient.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    return conn


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            phone TEXT NOT NULL
        )
        """
    )
    conn.commit()

    # Seed a couple of rows the first time so demos have data to show.
    count = conn.execute("SELECT COUNT(*) AS c FROM patients").fetchone()["c"]
    if count == 0:
        conn.executemany(
            "INSERT INTO patients (name, age, gender, phone) VALUES (?,?,?,?)",
            [
                ("Ravi Kumar", 34, "M", "9990001111"),
                ("Sneha Rao", 28, "F", "9990002222"),
            ],
        )
        conn.commit()
    conn.close()
