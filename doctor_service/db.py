import csv
import os
import sqlite3


# Location of the database
DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "doctor.db"
)

# Location of our CSV file
CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "doctors.csv"
)


def get_connection():
    """Create and return a connection to the doctor database."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    """Create the doctors table and import doctors from the CSV file."""

    connection = get_connection()

    # Create the table if it does not already exist
    connection.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            specialization TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            clinic_id TEXT,
            available_slots INTEGER NOT NULL DEFAULT 5
        )
    """)

    connection.commit()

    # Check whether doctors are already present
    count = connection.execute(
        "SELECT COUNT(*) AS total FROM doctors"
    ).fetchone()["total"]

    # Import the CSV only when the database is empty
    if count == 0:

        if not os.path.exists(CSV_PATH):
            print("doctors.csv was not found.")
            connection.close()
            return

        with open(CSV_PATH, "r", newline="", encoding="utf-8") as file:

            doctors = csv.DictReader(file)

            for doctor in doctors:

                # CSV uses IDs like D1, D2, D3.
                # Our API uses integer IDs, so D1 becomes 1.
                doctor_id = int(doctor["doctor_id"].replace("D", ""))

                connection.execute("""
                    INSERT INTO doctors
                    (id, name, specialization, phone, email,
                     clinic_id, available_slots)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    doctor_id,
                    doctor["full_name"],
                    doctor["specialty"],
                    doctor["phone"],
                    doctor["email"],
                    doctor["clinic_id"],
                    5
                ))

        connection.commit()

        print("Doctors imported successfully from doctors.csv.")

    else:
        print("Doctor database already contains data.")

    connection.close()


if __name__ == "__main__":
    init_db()