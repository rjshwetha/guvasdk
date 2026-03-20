from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from eligibility_verification import router as eligibility_router
from claims_status_inquiry import router as claims_router
from patient_ar_followup import router as patient_ar_router

import uuid
import json
import os
from datetime import datetime

app = FastAPI()
app.include_router(eligibility_router)
app.include_router(claims_router)
app.include_router(patient_ar_router)

CALLS_FILE = "calls.json"

VALID_CONTROLLERS = {
    "appointment": ["a", "b", "c"],
    "satisfaction": ["a", "b", "c"],
    "patient_ar": ["a", "b", "c"],
    "billing": ["a", "b", "c"],
    "denial": ["a", "b"],
    "payer_ar": ["a", "b"],
    "eligibility": ["a", "b"],
    "claims": ["a", "b"]
}


# ---------- Utility functions ----------

def load_calls():
    if not os.path.exists(CALLS_FILE):
        return []
    with open(CALLS_FILE, "r") as f:
        return json.load(f)


def save_calls(data):
    with open(CALLS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def update_status(call_id, status):
    calls = load_calls()
    for call in calls:
        if call["id"] == call_id:
            call["status"] = status
            call["updated_at"] = datetime.utcnow().isoformat()
    save_calls(calls)


# ---------- API ----------

@app.post("/call")
def make_call(controller: str, scenario: str, phone: str):

    if controller not in VALID_CONTROLLERS:
        raise HTTPException(status_code=400, detail="Invalid controller")

    if scenario not in VALID_CONTROLLERS[controller]:
        raise HTTPException(status_code=400, detail="Invalid scenario")

    call_id = str(uuid.uuid4())

    call_record = {
        "id": call_id,
        "controller": controller,
        "scenario": scenario,
        "phone": phone,
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }

    calls = load_calls()
    calls.append(call_record)
    save_calls(calls)

    return {
        "message": "Call initiated",
        "call_id": call_id
    }


@app.get("/calls")
def get_all_calls():
    return load_calls()


@app.get("/call/{call_id}")
def get_call(call_id: str):
    calls = load_calls()
    for call in calls:
        if call["id"] == call_id:
            return call
    raise HTTPException(status_code=404, detail="Call not found")


# ---------- Call Logs ----------

@app.get("/logs")
def get_all_logs():
    """Get all call logs"""
    calls = load_calls()
    if not calls:
        return {"total": 0, "logs": []}
    return {
        "total": len(calls),
        "logs": calls
    }


@app.get("/logs/{call_id}")
def get_log_by_call_id(call_id: str):
    """Get log for a specific call by call_id"""
    calls = load_calls()
    logs = [c for c in calls if c.get("call_id") == call_id or c.get("id") == call_id]
    if not logs:
        raise HTTPException(status_code=404, detail="No logs found for this call_id")
    return {
        "call_id": call_id,
        "total_events": len(logs),
        "logs": logs
    }


@app.get("/logs/status/{status}")
def get_logs_by_status(status: str):
    """Get all logs filtered by status (initiated, completed, no_answer, failed)"""
    calls = load_calls()
    filtered = [c for c in calls if c.get("status") == status]
    if not filtered:
        return {"total": 0, "status": status, "logs": []}
    return {
        "total": len(filtered),
        "status": status,
        "logs": filtered
    }


@app.get("/logs/type/{call_type}")
def get_logs_by_type(call_type: str):
    """Get all logs filtered by type (eligibility, appointment, billing, etc.)"""
    calls = load_calls()
    filtered = [c for c in calls if c.get("type") == call_type]
    if not filtered:
        return {"total": 0, "type": call_type, "logs": []}
    return {
        "total": len(filtered),
        "type": call_type,
        "logs": filtered
    }


@app.delete("/logs")
def clear_all_logs():
    """Clear all call logs"""
    save_calls([])
    return {"message": "All logs cleared"}


@app.get("/")
def read_root():
    return {"message": "Hello, API is working!"}
