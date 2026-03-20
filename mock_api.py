"""
Sarva Health — Mock API
=======================
Simulates the patient billing / EHR integration that Sarva Health's RCM
platform would call in production.

  patient_ar_followup.py — POST /patient/verify  (identity gate + balance lookup)

In production, replace each function body with the corresponding HTTP request
to your EHR or billing system (Epic, Athena, Kareo, etc.).
"""

import json

# ---------------------------------------------------------------------------
# Mock patient data  (replace with live EHR/billing data in production)
# ---------------------------------------------------------------------------

MOCK_PATIENTS: dict[str, dict] = {
    "BCBS9876543": {
        "patient_name": "Maria Chen",
        "dob": "1972-07-18",
        "member_id": "BCBS9876543",
        "balance": "$342.00",
        "dos": "January 28, 2026",
        "description": "Office visit — patient responsibility after BCBS applied deductible",
    },
    "UHC4412398": {
        "patient_name": "James Torres",
        "dob": "1961-03-29",
        "member_id": "UHC4412398",
        "balance": "$189.50",
        "dos": "December 10, 2025",
        "description": "Annual wellness exam — patient responsibility after insurance",
    },
    "AETNA7719284": {
        "patient_name": "Sandra Kim",
        "dob": "1988-11-15",
        "member_id": "AETNA7719284",
        "balance": "$775.00",
        "dos": "February 3, 2026",
        "description": "Physical therapy — 3 sessions, deductible applied",
    },
}

# ---------------------------------------------------------------------------
# Terminal logging helpers
# ---------------------------------------------------------------------------

def _log_request(method: str, path: str, payload: dict) -> None:
    print(f"\n{'─' * 58}")
    print(f"  → {method} {path}")
    print(f"    {json.dumps(payload)}")

def _log_response(status: int, payload: object) -> None:
    label = {200: "OK", 404: "Not Found"}.get(status, "")
    print(f"  ← {status} {label}")
    print(f"    {json.dumps(payload)}")
    print(f"{'─' * 58}\n")

# ---------------------------------------------------------------------------
# API stubs
# ---------------------------------------------------------------------------

def api_verify_patient_identity(member_id_or_ssn4: str, dob) -> dict | None:
    """
    POST /patient/verify

    Two-factor identity gate for outbound AR follow-up calls.
    Accepts the member ID (or last 4 digits) and date of birth provided
    by the patient during the call.

    Returns patient balance and DOS on success; None on identity mismatch.
    """
    # Normalize DOB from a date field dict or raw string
    if isinstance(dob, dict):
        try:
            dob_str = f"{dob['year']}-{dob['month']:02d}-{dob['day']:02d}"
        except (KeyError, TypeError):
            dob_str = str(dob)
    else:
        dob_str = str(dob or "")

    identifier = (member_id_or_ssn4 or "").strip()
    _log_request("POST", "/patient/verify", {"member_id_or_ssn4": identifier, "dob": dob_str})

    for patient in MOCK_PATIENTS.values():
        member_id = patient["member_id"]
        id_match = identifier == member_id or identifier == member_id[-4:]
        dob_match = dob_str == patient["dob"]
        if id_match and dob_match:
            resp = {
                "verified": True,
                "patient_name": patient["patient_name"],
                "balance": patient["balance"],
                "dos": patient["dos"],
                "description": patient["description"],
            }
            _log_response(200, resp)
            return resp

    # Return the same error regardless of which factor failed —
    # revealing a partial hit (e.g. DOB matched but name didn't) would be a HIPAA risk.
    _log_response(404, {"verified": False, "error": "IDENTITY_MISMATCH"})
    return None
