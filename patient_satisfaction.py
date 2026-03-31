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

from settings import ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME, CALLBACK_NUMBER

logging.basicConfig(level=logging.INFO)
logging.getLogger("guava").setLevel(logging.INFO)

router = APIRouter(prefix="/satisfaction", tags=["Satisfaction"])

CALLS_FILE = "calls.json"


# --------------------------------------------
# Logging helper (same everywhere)
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
class PatientSatisfactionController(guava.CallController):

    def __init__(self, patient_name, visit_date, call_id):
        super().__init__()

        self.patient_name = patient_name
        self.visit_date = visit_date
        self.call_id = call_id

        self.intent_classifier = IntentRecognizer({
            "opt_out": "Do not call",
            "clinical_concern": "Clinical issue",
            "dissatisfied": "Complaint",
            "very_positive": "Positive",
            "other": "Other"
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose="Conduct a short patient satisfaction survey",
        )

        self.reach_person(
            contact_full_name=self.patient_name,
            greeting=f"Hello, this is {AGENT_NAME} calling about your recent visit. May I speak with {self.patient_name}?",
            on_success=self.verify_contact,
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
    def verify_contact(self):
        log_call({
            "call_id": self.call_id,
            "status": "in_progress"
        })

        self.set_task(
            objective="Confirm identity and willingness",
            checklist=[
                guava.Field(
                    "availability",
                    "Is patient available?",
                    "multiple_choice",
                    True,
                    choices=["yes", "no", "do_not_contact"],
                )
            ],
            on_complete=self.route,
        )

    def route(self):
        availability = self.get_field("availability")

        if availability == "do_not_contact":
            log_call({"call_id": self.call_id, "status": "opt_out"})
            self.hangup("You will not receive further calls. Thank you.")
        elif availability == "no":
            self.decline()
        else:
            self.survey()

    # --------------------------------------------
    def survey(self):
        self.set_task(
            objective="Collect satisfaction feedback",
            checklist=[
                guava.Field("overall", "Overall experience (1-5)", "integer", True),
                guava.Field("communication", "Provider communication (1-5)", "integer"),
                guava.Field("wait_time", "Wait time (1-5)", "integer"),
                guava.Field("staff", "Staff friendliness (1-5)", "integer"),
                guava.Field("feedback", "Additional feedback", "text"),
                guava.Field("recommend", "Recommend practice (1-5)", "integer"),
            ],
            on_complete=self.end_call,
        )

    def decline(self):
        self.set_task(
            objective="Survey declined",
            checklist=[
                "Thank patient politely"
            ],
            on_complete=self.end_call,
        )

    def end_call(self):
        self.hangup("Thank you for your time")

    def handle_no_answer(self):
        log_call({
            "call_id": self.call_id,
            "status": "no_answer"
        })
        self.hangup("No answer")

    # --------------------------------------------
    @override
    def on_intent(self, intent: str):
        if self.intent_classifier.classify(intent) == "opt_out":
            log_call({"call_id": self.call_id, "status": "opt_out"})
            self.hangup("You have been removed from the list")

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
            "patient_name": self.patient_name,
            "overall": self.get_field("overall"),
            "recommend": self.get_field("recommend"),
            "transcript": transcript
        }

        log_call({
            "call_id": self.call_id,
            "type": "satisfaction",
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
            "type": "satisfaction",
            "to": phone,
            "status": "initiated",
            "transcript": []
        })

        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=PatientSatisfactionController(
                patient_name=payload.get("patient_name"),
                visit_date=payload.get("visit_date"),
                call_id=call_id
            ),
        )

        return {"call_id": call_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))