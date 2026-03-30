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

logging.basicConfig(level=logging.INFO)
logging.getLogger("guava").setLevel(logging.INFO)

router = APIRouter(prefix="/eligibility", tags=["Eligibility"])

CALLS_FILE = "calls.json"

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

    # -------- Transcript --------
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

    # -------- Flow --------
    def provide_info(self):
        log_call({
            "call_id": self.call_id,
            "status": "in_progress",
            "event": "reached_person"
        })

        self.set_task(
            objective="Provide NPI and patient details",
            checklist=[
                "Provide provider NPI",
                "Provide patient details",
                guava.Field(
                    key="rep_name",
                    description="Representative name",
                    type="text",
                    required=False
                ),
                guava.Field(
                    key="reference_number",
                    description="Reference number",
                    type="text",
                    required=False
                ),
            ],
            on_complete=self.collect_result,
        )

    def collect_result(self):
        self.set_task(
            objective="Collect eligibility details",
            checklist=[
                guava.Field(
                    key="eligibility_status",
                    description="Coverage status",
                    type="multiple_choice",
                    choices=["active", "termed", "pending", "unable_to_verify"],
                    required=True,
                ),
                guava.Field(
                    key="deductible_remaining",
                    description="Remaining deductible",
                    type="text"
                ),
                guava.Field(
                    key="copay_amount",
                    description="Copay amount",
                    type="text"
                ),
                guava.Field(
                    key="in_network_status",
                    description="Network status",
                    type="multiple_choice",
                    choices=["in_network", "out_of_network", "not_confirmed"],
                ),
            ],
            on_complete=self.end_call,
        )

    def end_call(self):
        status = self.get_field("eligibility_status")

        if status == "termed":
            self.set_task(
                objective="Collect termination details",
                checklist=[
                    guava.Field(
                        key="termination_date",
                        description="Termination date",
                        type="text"
                    ),
                    guava.Field(
                        key="termination_reason",
                        description="Reason",
                        type="text"
                    ),
                ],
                on_complete=lambda: self.hangup("Ending call"),
            )
        else:
            self.hangup("Thank you")

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
            "eligibility_status": self.get_field("eligibility_status"),
            "transcript": transcript
        }

        log_call({
            "call_id": self.call_id,
            "type": "eligibility",
            "status": "completed",
            "result": result
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


@router.post("/start")
def start_call(payload: dict):
    try:
        call_id = str(uuid.uuid4())
        phone = payload.get("phone")

        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        log_call({
            "call_id": call_id,
            "type": "eligibility",
            "to": phone,
            "status": "initiated",
            "transcript": []
        })

        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=EligibilityVerificationController(
                patient_name=payload.get("patient_name"),
                member_id=payload.get("member_id"),
                patient_dob=payload.get("dob"),
                dos=payload.get("dos"),
                call_id=call_id
            ),
        )

        return {"call_id": call_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))