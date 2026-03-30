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

from settings import ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME, PROVIDER_NPI, TAX_ID

logging.basicConfig(level=logging.INFO)
logging.getLogger("guava").setLevel(logging.INFO)

router = APIRouter(prefix="/claims", tags=["Claims"])

CALLS_FILE = "calls.json"

CLAIMS_SCENARIOS = {
    "a": {
        "label": "Claim in processing — expected payment in 10–14 days",
        "kwargs": {
            "claim_number": "CLM-2026-00489",
            "submission_date": "2026-02-15",
            "member_id": "BCBS9876543",
            "dos": "2026-01-28",
        },
    },
    "b": {
        "label": "Claim not found — resubmission guidance collected",
        "kwargs": {
            "claim_number": "CLM-2026-00221",
            "submission_date": "2026-01-10",
            "member_id": "UHC4412398",
            "dos": "2025-12-20",
        },
    },
}

# ---------------- LOGGING ----------------
def log_call(data):
    try:
        if not os.path.exists(CALLS_FILE):
            with open(CALLS_FILE, "w") as f:
                json.dump([], f)

        with open(CALLS_FILE, "r") as f:
            calls = json.load(f)

        call_id = data.get("call_id")
        updated = False

        for i, call in enumerate(calls):
            if call.get("call_id") == call_id:

                if "transcript_append" in data:
                    if "transcript" not in call:
                        call["transcript"] = []
                    call["transcript"].append(data["transcript_append"])
                    del data["transcript_append"]

                calls[i].update(data)
                calls[i]["updated_at"] = datetime.now().isoformat()
                updated = True
                break

        if not updated:
            data["created_at"] = datetime.now().isoformat()
            data["updated_at"] = datetime.now().isoformat()
            calls.append(data)

        with open(CALLS_FILE, "w") as f:
            json.dump(calls, f, indent=2)

    except Exception as e:
        logging.error(f"Logging failed: {e}")


# ---------------- CONTROLLER ----------------
class ClaimsStatusInquiryController(guava.CallController):

    def __init__(self, claim_number, submission_date, member_id, dos, call_id, provider_name=PROVIDER_NAME):
        super().__init__()

        self.claim_number = claim_number
        self.submission_date = submission_date
        self.member_id = member_id
        self.dos = dos
        self.call_id = call_id
        self.provider_name = provider_name

        self.intent_classifier = IntentRecognizer({
            "wrong_department": "Wrong department",
            "other": "Other"
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose="Check claim status"
        )

        self.add_info("Provider Name", provider_name)
        self.add_info("Provider NPI", PROVIDER_NPI)
        self.add_info("Provider Tax ID", TAX_ID)
        self.add_info("Claim Number", claim_number)
        self.add_info("Submission Date", submission_date)
        self.add_info("Member ID", member_id)
        self.add_info("DOS", dos)

        self.reach_person(
            contact_full_name="Claims Rep",
            on_success=self.provide_info,
            on_failure=self.handle_no_answer
        )

    # -------- TRANSCRIPT --------
    def add_transcript(self, speaker, text):
        log_call({
            "call_id": self.call_id,
            "transcript_append": {
                "speaker": speaker,
                "text": text,
                "time": datetime.now().isoformat()
            }
        })

    @override
    def on_message(self, message: dict):
        try:
            if message.get("type") in ["user_input", "user_message"]:
                if message.get("text"):
                    self.add_transcript("user", message["text"])

            elif message.get("type") in ["assistant_response", "assistant_message"]:
                if message.get("text"):
                    self.add_transcript("agent", message["text"])

        except Exception as e:
            logging.error(f"Transcript error: {e}")

    # -------- FLOW --------
    def provide_info(self):
        log_call({
            "call_id": self.call_id,
            "status": "in_progress",
            "event": "reached_person"
        })

        self.set_task(
            objective="Provide claim details",
            checklist=[
                "Provide NPI and Tax ID",
                "Provide claim details"
            ],
            on_complete=self.collect_status
        )

    def collect_status(self):
        self.set_task(
            objective="Collect claim status",
            checklist=[
                guava.Field(
                    key="claim_status",
                    description="Claim status",
                    type="multiple_choice",
                    choices=["received_processing", "pending_info", "denied", "paid", "not_found"],
                    required=True
                ),
                guava.Field(
                    key="expected_payment_date",
                    description="Expected payment date",
                    type="text"
                ),
                guava.Field(
                    key="payment_amount",
                    description="Payment amount",
                    type="text"
                ),
                guava.Field(
                    key="denial_reason",
                    description="Denial reason",
                    type="text"
                ),
                guava.Field(
                    key="additional_info_needed",
                    description="Additional info needed",
                    type="text"
                ),
                guava.Field(
                    key="rep_name",
                    description="Rep name",
                    type="text"
                ),
            ],
            on_complete=self.end_call
        )

    def end_call(self):
        status = self.get_field("claim_status")

        log_call({
            "call_id": self.call_id,
            "event": "claim_status_collected",
            "claim_status": status
        })

        self.hangup("Thank you")

    # -------- SESSION DONE --------
    @override
    def on_session_done(self):
        transcript = []

        if os.path.exists(CALLS_FILE):
            with open(CALLS_FILE, "r") as f:
                calls = json.load(f)
                for call in calls:
                    if call.get("call_id") == self.call_id:
                        transcript = call.get("transcript", [])

        summary = " | ".join([t["text"] for t in transcript[:3]]) if transcript else None

        result = {
            "call_id": self.call_id,
            "claim_number": self.claim_number,
            "claim_status": self.get_field("claim_status"),
            "expected_payment_date": self.get_field("expected_payment_date"),
            "payment_amount": self.get_field("payment_amount"),
            "denial_reason": self.get_field("denial_reason"),
            "additional_info_needed": self.get_field("additional_info_needed"),
            "rep_name": self.get_field("rep_name"),
        }

        log_call({
            "call_id": self.call_id,
            "type": "claims",
            "status": "completed",
            "result": result,
            "transcript": transcript,
            "summary": summary
        })

    def handle_no_answer(self):
        log_call({
            "call_id": self.call_id,
            "status": "no_answer"
        })
        self.hangup("No answer")

    @override
    def on_intent(self, intent: str):
        if self.intent_classifier.classify(intent) == "wrong_department":
            log_call({
                "call_id": self.call_id,
                "status": "failed"
            })
            self.hangup("Wrong department")


# ---------------- API ----------------
@router.post("/start")
def start_claim(payload: dict):
    try:
        call_id = str(uuid.uuid4())
        phone = payload.get("phone")
        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        log_call({
            "call_id": call_id,
            "type": "claims",
            "to": phone,
            "status": "initiated",
            "transcript": []
        })

        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=ClaimsStatusInquiryController(
                claim_number=payload.get("claim_number"),
                submission_date=payload.get("submission_date"),
                member_id=payload.get("member_id"),
                dos=payload.get("dos"),
                call_id=call_id
            ),
        )

        return {"call_id": call_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))