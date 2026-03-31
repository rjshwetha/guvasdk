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
from guava.helpers.openai import DocumentQA

from settings import (
    ORGANIZATION_NAME,
    AGENT_NAME,
    PROVIDER_NAME,
    CALLBACK_NUMBER,
    PATIENT_PORTAL_URL,
    TRANSFER_NUMBER,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("guava").setLevel(logging.INFO)

router = APIRouter(prefix="/billing", tags=["Billing"])

CALLS_FILE = "calls.json"

# --------------------------------------------
# Load FAQ
# --------------------------------------------
FAQ_PATH = os.path.join(os.path.dirname(__file__), "billing_faq.md")
with open(FAQ_PATH) as f:
    FAQ_DOC = f.read()


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
class BillingStatementController(guava.CallController):

    def __init__(
        self,
        patient_name,
        patient_dob,
        member_id,
        balance,
        dos,
        insurance_paid,
        call_id,
    ):
        super().__init__()

        self.patient_name = patient_name
        self.patient_dob = patient_dob
        self.member_id = member_id
        self.balance = balance
        self.dos = dos
        self.insurance_paid = insurance_paid
        self.call_id = call_id

        self.billing_faq = DocumentQA("billing-faq", FAQ_DOC)

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose="Inform patient about billing statement and assist with next steps",
        )

        self.add_info("Provider Name", PROVIDER_NAME)
        self.add_info("Callback Number", CALLBACK_NUMBER)
        self.add_info("Portal URL", PATIENT_PORTAL_URL)

        self.reach_person(
            contact_full_name=self.patient_name,
            greeting=f"Hello, may I speak with {self.patient_name}?",
            on_success=self.verify_identity,
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
    # Identity Verification
    # --------------------------------------------
    def verify_identity(self):
        log_call({
            "call_id": self.call_id,
            "status": "in_progress",
            "event": "verify_identity"
        })

        self.set_task(
            objective="Verify identity before sharing billing details",
            checklist=[
                guava.Say("I need to verify your identity."),
                guava.Field("dob", "Date of birth", "date", True),
                guava.Field("member", "Member ID or last 4 SSN", "text", True),
            ],
            on_complete=self.check_identity,
        )

    def check_identity(self):
        dob = self.get_field("dob")
        member = self.get_field("member")

        try:
            dob_str = f"{dob['year']}-{dob['month']:02d}-{dob['day']:02d}"
        except:
            return self.identity_failed()

        if dob_str == self.patient_dob and (
            member == self.member_id or member == self.member_id[-4:]
        ):
            self.deliver_statement()
        else:
            self.identity_failed()

    def identity_failed(self):
        log_call({
            "call_id": self.call_id,
            "status": "failed_identity"
        })

        self.hangup(
            f"Unable to verify identity. Please call {CALLBACK_NUMBER} or visit portal."
        )

    # --------------------------------------------
    # Statement
    # --------------------------------------------
    def deliver_statement(self):
        self.set_task(
            objective="Explain billing statement",
            checklist=[
                guava.Say(
                    f"Your balance is {self.balance} for services on {self.dos}. "
                    f"Insurance paid {self.insurance_paid}."
                ),
                guava.Field(
                    key="intent",
                    description="What patient wants",
                    type="multiple_choice",
                    choices=[
                        "pay_online",
                        "pay_phone",
                        "billing_rep",
                        "question",
                        "itemized",
                        "no_action",
                    ],
                    required=True,
                ),
            ],
            on_complete=self.route,
        )

    # --------------------------------------------
    # Routing
    # --------------------------------------------
    def route(self):
        intent = self.get_field("intent")

        log_call({
            "call_id": self.call_id,
            "intent": intent
        })

        if intent == "pay_online":
            self.hangup(f"Please pay at {PATIENT_PORTAL_URL}")

        elif intent == "pay_phone":
            self.hangup("You can pay securely via phone keypad.")

        elif intent == "billing_rep":
            if TRANSFER_NUMBER:
                self.transfer(TRANSFER_NUMBER)
            else:
                self.hangup(f"Our billing team will call you back at {CALLBACK_NUMBER}")

        elif intent == "question":
            self.set_task(
                objective="Handle question",
                checklist=[
                    guava.Field("question", "Patient question", "text")
                ],
                on_complete=self.end_call,
            )

        elif intent == "itemized":
            self.hangup("We will send an itemized bill shortly.")

        else:
            self.end_call()

    # --------------------------------------------
    def end_call(self):
        self.hangup("Thank you")

    def handle_no_answer(self):
        log_call({
            "call_id": self.call_id,
            "status": "no_answer"
        })
        self.hangup("No answer")

    @override
    def on_question(self, question: str) -> str:
        return self.billing_faq.ask(question)

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
            "intent": self.get_field("intent"),
            "transcript": transcript
        }

        log_call({
            "call_id": self.call_id,
            "type": "billing",
            "status": "completed",
            "result": result
        })


# ============================================
# API ENDPOINT (MATCHES ELIGIBILITY)
# ============================================
@router.post("/start")
def start_call(payload: dict):
    try:
        call_id = str(uuid.uuid4())
        phone = payload.get("phone")

        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        log_call({
            "call_id": call_id,
            "type": "billing",
            "to": phone,
            "status": "initiated",
            "transcript": []
        })

        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=BillingStatementController(
                patient_name=payload.get("patient_name"),
                patient_dob=payload.get("dob"),
                member_id=payload.get("member_id"),
                balance=payload.get("balance"),
                dos=payload.get("dos"),
                insurance_paid=payload.get("insurance_paid"),
                call_id=call_id
            ),
        )

        return {"call_id": call_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))