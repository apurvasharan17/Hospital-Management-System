
import os

try:
    from dotenv import load_dotenv
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_ROOT, ".env"))
except Exception: 
    pass


def _get(name, default):
    value = os.environ.get(name)
    return value if value not in (None, "") else default

REGISTRY_PORT = int(_get("REGISTRY_PORT", "5000"))
PATIENT_PORT = int(_get("PATIENT_PORT", "5001"))
DOCTOR_PORT = int(_get("DOCTOR_PORT", "5002"))
APPOINTMENT_PORT = int(_get("APPOINTMENT_PORT", "5003"))
BILLING_PORT = int(_get("BILLING_PORT", "5004"))
GATEWAY_PORT = int(_get("GATEWAY_PORT", "8080"))
HOST = _get("HOST", "127.0.0.1")

REGISTRY_URL = _get("REGISTRY_URL", f"http://{HOST}:{REGISTRY_PORT}")


def public_url(port):
    return f"http://{HOST}:{port}"