from dotenv import load_dotenv
load_dotenv()

import guava
import os
import json
import logging
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from typing_extensions import override
from guava.helpers.openai import IntentRecognizer

from settings import ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME, PROVIDER_NPI

# ---------------------------------------
# Setup
# ---------------------------------------

logging.basicConfig(level=logging.INFO)
logging.getLogger("guava").setLevel(logging.INFO)

router = APIRouter(prefix="/eligibility", tags=["Eligibility"])

CALLS_FILE = "calls.json"

# ---------------------------------------
# Scenario Registry
# ---------------------------------------
ELIGIBILITY_SCENARIOS = {
    "a": {
        "label": "Coverage active — deductible remaining + copay confirmed",
        "kwargs": {
            "patient_name": "Jane Smith",
            "member_id": "UHC1234567",
            "patient_dob": "03/15/1978",
            "dos": "2026-04-15",
        },
    },
    "b": {
        "label": "Coverage termed — termination date and reason collected",
        "kwargs": {
            "patient_name": "Robert Davis",
            "member_id": "BCBS7890123",
            "patient_dob": "08/22/1961",
            "dos": "2026-04-10",
        },
    },
}


# ---------------------------------------
# Utility: Logging Calls
# ---------------------------------------
def log_call(data):
    try:
        if not os.path.exists(CALLS_FILE):
            with open(CALLS_FILE, "w") as f:
                json.dump([], f)

        with open(CALLS_FILE, "r") as f:
            calls = json.load(f)

        # ✅ Update existing log entry if call_id matches
        call_id = data.get("call_id")
        updated = False

        if call_id:
            for i, call in enumerate(calls):
                if call.get("call_id") == call_id:
                    calls[i].update(data)
                    calls[i]["updated_at"] = datetime.now().isoformat()
                    updated = True
                    break

        # ✅ If no existing entry found, append new one
        if not updated:
            data["created_at"] = datetime.now().isoformat()
            data["updated_at"] = datetime.now().isoformat()
            calls.append(data)

        with open(CALLS_FILE, "w") as f:
            json.dump(calls, f, indent=2)

    except Exception as e:
        logging.error(f"Logging failed: {e}")


# ---------------------------------------
# Controller
# ---------------------------------------
class EligibilityVerificationController(guava.CallController):

    def __init__(self, patient_name, member_id, patient_dob, dos, call_id):
        super().__init__()

        self.patient_name = patient_name
        self.member_id = member_id
        self.patient_dob = patient_dob
        self.dos = dos
        self.call_id = call_id

        self.intent_classifier = IntentRecognizer({
            "wrong_department": "Wrong department or cannot help",
            "other": "Anything else"
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose="Verify patient insurance eligibility before service"
        )

        self.add_info("Provider Name", PROVIDER_NAME)
        self.add_info("Provider NPI", PROVIDER_NPI)
        self.add_info("Patient Member ID", member_id)
        self.add_info("Patient DOB", patient_dob)
        self.add_info("DOS", dos)

        self.reach_person(
            contact_full_name="Provider Services Rep",
            on_success=self.provide_info,
            on_failure=self.handle_no_answer,
        )

    # ---------------------------------------
    def provide_info(self):
        # ✅ Log when agent reaches person
        log_call({
            "call_id": self.call_id,
            "status": "in_progress",
            "event": "reached_person",
            "event_time": datetime.now().isoformat()
        })

        self.set_task(
            objective="Provide NPI and patient details as requested",
            checklist=[
                "Provide provider NPI",
                "Provide patient member ID, DOB, DOS",
                guava.Field("rep_name", "Representative name", "text", required=False),
                guava.Field("reference_number", "Reference number", "text", required=False),
            ],
            on_complete=self.collect_result,
        )

    # ---------------------------------------
    def collect_result(self):
        # ✅ Log when info is provided
        log_call({
            "call_id": self.call_id,
            "event": "info_provided",
            "rep_name": self.get_field("rep_name"),
            "reference_number": self.get_field("reference_number"),
            "event_time": datetime.now().isoformat()
        })

        self.set_task(
            objective="Collect eligibility details",
            checklist=[
                guava.Field(
                    "eligibility_status",
                    "Coverage status",
                    "multiple_choice",
                    choices=["active", "termed", "pending", "unable_to_verify"],
                    required=True,
                ),
                guava.Field("deductible_remaining", "Remaining deductible", "text"),
                guava.Field("copay_amount", "Copay amount", "text"),
                guava.Field(
                    "in_network_status",
                    "Network status",
                    "multiple_choice",
                    choices=["in_network", "out_of_network", "not_confirmed"],
                ),
            ],
            on_complete=self.end_call,
        )

    # ---------------------------------------
    def end_call(self):
        status = self.get_field("eligibility_status")

        # ✅ Log eligibility result
        log_call({
            "call_id": self.call_id,
            "event": "eligibility_collected",
            "eligibility_status": status,
            "deductible_remaining": self.get_field("deductible_remaining"),
            "copay_amount": self.get_field("copay_amount"),
            "in_network_status": self.get_field("in_network_status"),
            "event_time": datetime.now().isoformat()
        })

        if status == "termed":
            self.set_task(
                objective="Collect termination details",
                checklist=[
                    guava.Field("termination_date", "Termination date", "text"),
                    guava.Field("termination_reason", "Reason", "text"),
                ],
                on_complete=lambda: self.hangup("Thank you, ending call."),
            )

        elif status == "unable_to_verify":
            self.set_task(
                objective="Collect callback info",
                checklist=[
                    guava.Field("callback_number", "Callback number", "text"),
                ],
                on_complete=lambda: self.hangup("We will follow up."),
            )
        else:
            self.hangup("Thank you for the information.")

    # ---------------------------------------
    @override
    def on_session_done(self):
        result = {
            "call_id": self.call_id,
            "timestamp": datetime.now().isoformat(),
            "patient_name": self.patient_name,
            "eligibility_status": self.get_field("eligibility_status"),
            "deductible_remaining": self.get_field("deductible_remaining"),
            "copay_amount": self.get_field("copay_amount"),
            "in_network_status": self.get_field("in_network_status"),
            "rep_name": self.get_field("rep_name"),
            "reference_number": self.get_field("reference_number"),
        }

        # ✅ Final log update with all results
        log_call({
            "call_id": self.call_id,
            "type": "eligibility",
            "status": "completed",
            "event": "session_done",
            "result": result,
            "completed_at": datetime.now().isoformat()
        })

        logging.info(f"Call {self.call_id} completed")

    # ---------------------------------------
    def handle_no_answer(self):
        # ✅ Log no answer
        log_call({
            "call_id": self.call_id,
            "status": "no_answer",
            "event": "no_answer",
            "event_time": datetime.now().isoformat()
        })
        self.hangup("Unable to reach representative.")

    # ---------------------------------------
    @override
    def on_intent(self, intent: str):
        if self.intent_classifier.classify(intent) == "wrong_department":
            # ✅ Log wrong department
            log_call({
                "call_id": self.call_id,
                "status": "failed",
                "event": "wrong_department",
                "event_time": datetime.now().isoformat()
            })
            self.hangup("Sorry, wrong department.")


# ---------------------------------------
# API Endpoint: Start by Scenario
# ---------------------------------------
@router.post("/start/scenario")
def start_call_by_scenario(scenario: str, phone: str):
    """
    Mimics CLI run_demo.py behavior.
    Pass scenario = 'a' or 'b' and phone number.
    """
    try:
        if scenario not in ELIGIBILITY_SCENARIOS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scenario. Valid options: {list(ELIGIBILITY_SCENARIOS.keys())}"
            )

        call_id = str(uuid.uuid4())
        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        if not agent_number:
            raise HTTPException(status_code=500, detail="GUAVA_AGENT_NUMBER not set")

        sc = ELIGIBILITY_SCENARIOS[scenario]
        kwargs = sc["kwargs"]

        logging.info(f"Starting eligibility call | Scenario: {scenario} | Phone: {phone}")

        # ✅ Initial log entry
        log_call({
            "call_id": call_id,
            "type": "eligibility",
            "scenario": scenario,
            "label": sc["label"],
            "from": agent_number,
            "to": phone,
            "patient_name": kwargs["patient_name"],
            "member_id": kwargs["member_id"],
            "patient_dob": kwargs["patient_dob"],
            "dos": kwargs["dos"],
            "status": "initiated",
            "event": "call_initiated",
        })

        # ✅ Trigger call
        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=EligibilityVerificationController(
                patient_name=kwargs["patient_name"],
                member_id=kwargs["member_id"],
                patient_dob=kwargs["patient_dob"],
                dos=kwargs["dos"],
                call_id=call_id
            ),
        )

        return {
            "message": "Eligibility call started",
            "call_id": call_id,
            "scenario": scenario,
            "label": sc["label"],
            "patient_name": kwargs["patient_name"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Call failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------
# API Endpoint: Start with Custom Data
# ---------------------------------------
@router.post("/start")
def start_call(payload: dict):
    """
    Start eligibility call with custom patient data.
    """
    try:
        call_id = str(uuid.uuid4())

        phone = payload.get("phone")
        patient_name = payload.get("patient_name")
        member_id = payload.get("member_id")
        dob = payload.get("dob")
        dos = payload.get("dos")
        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        if not phone:
            raise HTTPException(status_code=400, detail="Phone required")

        if not agent_number:
            raise HTTPException(status_code=500, detail="GUAVA_AGENT_NUMBER not set")

        # ✅ Initial log entry
        log_call({
            "call_id": call_id,
            "type": "eligibility",
            "from": agent_number,
            "to": phone,
            "patient_name": patient_name,
            "member_id": member_id,
            "patient_dob": dob,
            "dos": dos,
            "status": "initiated",
            "event": "call_initiated",
        })
        logging.info(f"=== CALL DEBUG ===")
        logging.info(f"API KEY: {os.getenv('GUAVA_API_KEY')[:6]}...")  # Only first 6 chars for safety
        logging.info(f"AGENT NUMBER (from): {agent_number}")
        logging.info(f"CUSTOMER NUMBER (to): {phone}")
        logging.info(f"==================")
        # ✅ Trigger call
        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=EligibilityVerificationController(
                patient_name=patient_name,
                member_id=member_id,
                patient_dob=dob,
                dos=dos,
                call_id=call_id
            ),
        )

        return {
            "message": "Call started",
            "call_id": call_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Call failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------
# Get All Eligibility Calls
# ---------------------------------------
@router.get("/calls")
def get_calls():
    try:
        if not os.path.exists(CALLS_FILE):
            return []

        with open(CALLS_FILE, "r") as f:
            calls = json.load(f)

        # ✅ Filter only eligibility calls
        return [c for c in calls if c.get("type") == "eligibility"]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
