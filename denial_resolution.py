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
from guava.helpers.openai import DocumentQA, IntentRecognizer

from settings import ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME, PROVIDER_NPI

logging.basicConfig(level=logging.INFO)
logging.getLogger("guava").setLevel(logging.INFO)

router = APIRouter(prefix="/denial", tags=["Denial"])

CALLS_FILE = "calls.json"

# --------------------------------------------
# Load denial codes doc
# --------------------------------------------
DENIAL_CODES_PATH = os.path.join(os.path.dirname(__file__), "denial_codes.md")
with open(DENIAL_CODES_PATH) as f:
    DENIAL_DOC = f.read()


# --------------------------------------------
# Logging helper (same as eligibility)
# --------------------------------------------
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


# ============================================
# Controller
# ============================================
class DenialResolutionController(guava.CallController):

    def __init__(
        self,
        claim_number,
        member_id,
        denial_date,
        denial_code,
        call_id,
        provider_name=PROVIDER_NAME,
    ):
        super().__init__()

        self.claim_number = claim_number
        self.member_id = member_id
        self.denial_date = denial_date
        self.denial_code = denial_code
        self.provider_name = provider_name
        self.call_id = call_id

        self.denial_code_qa = DocumentQA("denial-codes", DENIAL_DOC)

        self.intent_classifier = IntentRecognizer({
            "authorization_request": "Authorization required",
            "wrong_department": "Wrong department",
            "other": "Other"
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose="Call payer to resolve denied claim and identify next steps",
        )

        self.add_info("Provider Name", provider_name)
        self.add_info("Provider NPI", PROVIDER_NPI)
        self.add_info("Claim Number", claim_number)
        self.add_info("Member ID", member_id)
        self.add_info("Denial Date", denial_date)
        self.add_info("Denial Code", denial_code)

        self.reach_person(
            contact_full_name="Provider Appeals Representative",
            on_success=self.verify_and_identify_denial,
            on_failure=self.handle_no_answer,
        )

    # --------------------------------------------
    # Transcript
    # --------------------------------------------
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

    # --------------------------------------------
    # Flow
    # --------------------------------------------
    def verify_and_identify_denial(self):
        log_call({
            "call_id": self.call_id,
            "status": "in_progress",
            "event": "identify_denial"
        })

        self.set_task(
            objective="Provide claim and denial details",
            checklist=[
                "Provide NPI, claim number, member ID, denial code",
            ],
            on_complete=self.collect_denial_details,
        )

    def collect_denial_details(self):
        self.set_task(
            objective="Collect denial details",
            checklist=[
                guava.Field("denial_code_confirmed", "Confirm denial code", "text", True),
                guava.Field("denial_reason_full", "Full reason", "text", True),
                guava.Field(
                    "resolution_path",
                    "Resolution path",
                    "multiple_choice",
                    True,
                    choices=[
                        "file_formal_appeal",
                        "submit_corrected_claim",
                        "provide_additional_docs",
                        "no_appeal_available",
                        "escalate_to_supervisor",
                    ],
                ),
                guava.Field("appeal_deadline", "Appeal deadline", "date"),
                guava.Field("appeal_fax_or_portal", "Submission method", "text"),
                guava.Field("rep_reference_number", "Reference number", "text"),
            ],
            on_complete=self.end_call,
        )

    def end_call(self):
        path = self.get_field("resolution_path")

        log_call({
            "call_id": self.call_id,
            "resolution_path": path
        })

        if path == "escalate_to_supervisor":
            self.request_supervisor()
        else:
            self.hangup("Thank you for the information")

    def request_supervisor(self):
        self.set_task(
            objective="Escalate to supervisor",
            checklist=[
                "Request supervisor",
                guava.Field("supervisor_resolution_path", "Supervisor resolution", "text"),
                guava.Field("supervisor_callback_number", "Callback number", "text"),
            ],
            on_complete=lambda: self.hangup("Thank you"),
        )

    def handle_no_answer(self):
        log_call({
            "call_id": self.call_id,
            "status": "no_answer"
        })
        self.hangup("No answer")

    # --------------------------------------------
    @override
    def on_question(self, question: str) -> str:
        return self.denial_code_qa.ask(question)

    @override
    def on_intent(self, intent: str):
        if self.intent_classifier.classify(intent) == "wrong_department":
            log_call({
                "call_id": self.call_id,
                "status": "failed"
            })
            self.hangup("Wrong department")

    @override
    def on_session_done(self):
        transcript = []

        if os.path.exists(CALLS_FILE):
            with open(CALLS_FILE, "r") as f:
                calls = json.load(f)
                for call in calls:
                    if call.get("call_id") == self.call_id:
                        transcript = call.get("transcript", [])

        result = {
            "call_id": self.call_id,
            "claim_number": self.claim_number,
            "resolution_path": self.get_field("resolution_path"),
            "transcript": transcript
        }

        log_call({
            "call_id": self.call_id,
            "type": "denial",
            "status": "completed",
            "result": result
        })


# ============================================
# API ENDPOINT
# ============================================
@router.post("/start")
def start_call(payload: dict):
    try:
        call_id = str(uuid.uuid4())
        phone = payload.get("phone")

        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        log_call({
            "call_id": call_id,
            "type": "denial",
            "to": phone,
            "status": "initiated",
            "transcript": []
        })

        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=DenialResolutionController(
                claim_number=payload.get("claim_number"),
                member_id=payload.get("member_id"),
                denial_date=payload.get("denial_date"),
                denial_code=payload.get("denial_code"),
                call_id=call_id
            ),
        )

        return {"call_id": call_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))