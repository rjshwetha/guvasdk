from dotenv import load_dotenv
load_dotenv()

import guava
import os
import sys
import json
import logging
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from typing_extensions import override
from guava.helpers.openai import IntentRecognizer

sys.path.insert(0, os.path.dirname(__file__))
from settings import ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME, CALLBACK_NUMBER
from mock_api import api_verify_patient_identity

logging.basicConfig(level=logging.INFO)
logging.getLogger('guava').setLevel(logging.INFO)

router = APIRouter(prefix="/patient-ar", tags=["Patient AR"])

CALLS_FILE = "calls.json"

# ---------------------------------------
# Scenario Registry (Matches run_demo.py)
# ---------------------------------------
PATIENT_AR_SCENARIOS = {
    "a": {
        "label": "Maria Chen — identity verified, pays by card ($342.00)",
        "kwargs": {
            "patient_name": "Maria Chen",
        },
    },
    "b": {
        "label": "James Torres — identity verified, disputes balance ($189.50)",
        "kwargs": {
            "patient_name": "James Torres",
        },
    },
    "c": {
        "label": "Sandra Kim — identity verified, requests payment plan ($775.00)",
        "kwargs": {
            "patient_name": "Sandra Kim",
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
class PatientARFollowUpController(guava.CallController):
    """
    Outbound patient AR follow-up call with HIPAA identity gate.

    Flow:
      __init__ → reach_person(on_success=verify_identity, on_failure=leave_voicemail)
        → verify_identity: collect DOB + member_id_or_ssn4 → check_identity_match
        → check_identity_match: API call → discuss_balance or identity_mismatch
        → discuss_balance: present balance, collect patient_response → route_by_response
        → (branch) payment | dispute | payment_plan | callback
        → end_call → hangup
    """

    def __init__(
        self,
        patient_name: str,
        call_id: str,
        provider_name: str = PROVIDER_NAME,
    ):
        super().__init__()
        self._patient_name = patient_name
        self._provider_name = provider_name
        self._call_id = call_id
        self._balance_amount: str | None = None
        self._dos: str | None = None

        self.intent_classifier = IntentRecognizer({
            "hostile_or_legal": (
                "Caller is expressing anger, hostility, or making legal threats — "
                "mentioning a lawyer, suing, reporting, or harassment."
            ),
            "deceased_patient": (
                "Caller indicates the patient has passed away, is deceased, or has died."
            ),
            "other": "Any other intent not covered above.",
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose=(
                "You are calling a patient on behalf of their healthcare provider's billing office "
                "regarding an outstanding account balance. You are professional, empathetic, and patient."
            ),
        )

        # Provider-level info only — no patient account data until identity is verified
        self.add_info("Billing Office", provider_name)
        self.add_info("Callback Number", CALLBACK_NUMBER)

        # HIPAA: greeting must NOT disclose the purpose of the call before identity is verified
        self.reach_person(
            contact_full_name=self._patient_name,
            greeting=f"Hello, may I please speak with {self._patient_name}?",
            on_success=self.verify_identity,
            on_failure=self.leave_voicemail,
        )

    # ------------------------------------------------------------------
    # Stage 2 — HIPAA identity verification
    # ------------------------------------------------------------------

    def verify_identity(self):
        logging.info("Stage: HIPAA identity gate — verifying patient: %s", self._patient_name)

        # ✅ Log reached person
        log_call({
            "call_id": self._call_id,
            "status": "in_progress",
            "event": "reached_person",
            "event_time": datetime.now().isoformat()
        })

        self.set_task(
            objective=(
                f"You've reached someone who may be {self._patient_name}. "
                "Before disclosing any account information, you must verify their identity. "
                "Collect their date of birth and member ID (or last four of SSN)."
            ),
            checklist=[
                guava.Say(
                    "Before I can discuss your account, I need to verify your identity. "
                    "I'll need your date of birth and the last four digits of your Social Security "
                    "Number — or the member ID from your insurance card."
                ),
                guava.Field(
                    key="verified_dob",
                    description="Patient's date of birth for identity verification.",
                    field_type="date",
                    required=True,
                ),
                guava.Field(
                    key="verified_member_id_or_ssn4",
                    description="Patient's member ID from their insurance card, or the last four digits of their SSN.",
                    field_type="text",
                    required=True,
                ),
            ],
            on_complete=self.check_identity_match,
        )

    def check_identity_match(self):
        dob = self.get_field("verified_dob")
        identifier = self.get_field("verified_member_id_or_ssn4")
        result = api_verify_patient_identity(identifier, dob)

        if result:
            logging.info("Identity verified — balance: %s, DOS: %s", result["balance"], result["dos"])
            self._balance_amount = result["balance"]
            self._dos = result["dos"]

            # ✅ Log identity verified
            log_call({
                "call_id": self._call_id,
                "event": "identity_verified",
                "balance_amount": self._balance_amount,
                "dos": self._dos,
                "event_time": datetime.now().isoformat()
            })

            self.discuss_balance()
        else:
            logging.info("Identity mismatch — routing to identity_mismatch()")

            # ✅ Log identity mismatch
            log_call({
                "call_id": self._call_id,
                "event": "identity_mismatch",
                "status": "failed",
                "event_time": datetime.now().isoformat()
            })

            self.identity_mismatch()

    def identity_mismatch(self):
        self.set_task(
            objective=(
                "The identity check did not pass. You cannot share any account information. "
                "Advise the caller to contact the billing office directly."
            ),
            checklist=[
                "Let the caller know that you were unable to verify their identity with the "
                "information provided and that for their security you cannot access account details. "
                "Provide the billing office callback number and encourage them to call directly.",
            ],
            on_complete=lambda: self.hangup(
                final_instructions=(
                    f"Direct the caller to reach our billing office at {CALLBACK_NUMBER}. "
                    "End the call politely and professionally."
                )
            ),
        )

    # ------------------------------------------------------------------
    # Stage 3 — Discuss balance
    # ------------------------------------------------------------------

    def discuss_balance(self):
        # Identity confirmed — now safe to load patient account data
        self.add_info("Outstanding Balance", self._balance_amount)
        self.add_info("Date of Service", self._dos)

        self.set_task(
            objective=(
                f"Identity verified. Present {self._patient_name}'s outstanding balance "
                f"and understand how they'd like to proceed."
            ),
            checklist=[
                guava.Say(
                    f"Thank you for verifying your identity. I'm calling from "
                    f"{self._provider_name}'s billing office. You have an outstanding patient "
                    f"balance of {self._balance_amount} related to services on {self._dos}."
                ),
                guava.Field(
                    key="patient_response",
                    description="How does the patient respond to the balance?",
                    field_type="multiple_choice",
                    choices=[
                        "wants_to_pay_now",
                        "disputes_balance",
                        "requests_payment_plan",
                        "says_already_paid",
                        "requests_callback",
                        "no_funds_available",
                    ],
                    required=True,
                ),
            ],
            on_complete=self.route_by_response,
        )

    def route_by_response(self):
        response = self.get_field("patient_response")
        logging.info("Patient response: %s", response)

        # ✅ Log patient response
        log_call({
            "call_id": self._call_id,
            "event": "patient_response_collected",
            "patient_response": response,
            "event_time": datetime.now().isoformat()
        })

        if response == "wants_to_pay_now":
            self._handle_payment()
        elif response in ("disputes_balance", "says_already_paid"):
            self._handle_dispute()
        elif response == "requests_payment_plan":
            self._handle_payment_plan()
        elif response == "requests_callback":
            self._handle_callback_request()
        else:
            # no_funds_available or other
            self.set_task(
                objective=(
                    "The patient indicated they cannot pay right now. "
                    "Offer payment plan options and close empathetically."
                ),
                checklist=[
                    guava.Say(
                        "We understand. We do offer flexible payment plans — our billing team can "
                        "work with you to find an arrangement that fits your situation."
                    ),
                    guava.Field(
                        key="payment_plan_interest",
                        description="Is the patient interested in hearing about payment plan options?",
                        field_type="multiple_choice",
                        choices=["yes", "no"],
                        required=True,
                    ),
                ],
                on_complete=lambda: (
                    self._handle_payment_plan()
                    if self.get_field("payment_plan_interest") == "yes"
                    else self.end_call()
                ),
            )

    # ------------------------------------------------------------------
    # Stage 4A — Payment
    # ------------------------------------------------------------------

    def _handle_payment(self):
        self.set_task(
            objective=(
                "The patient wants to pay now. For PCI compliance, payment by card should be "
                "handled via DTMF keypad entry (not read aloud). Inform the patient and collect "
                "the confirmation number once payment is processed."
            ),
            checklist=[
                "Inform the patient that payment can be processed securely. "
                "For card payments, direct them to enter their card number using their phone keypad "
                "for security — do not read card numbers aloud.",
                guava.Field(
                    key="payment_confirmation_number",
                    description="Confirmation number from the payment processor once payment is complete.",
                    field_type="text",
                    required=False,
                ),
                guava.Say(
                    "Your payment has been processed. You will receive a confirmation by email or mail. "
                    "Thank you."
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Stage 4B — Dispute
    # ------------------------------------------------------------------

    def _handle_dispute(self):
        self.set_task(
            objective=(
                "The patient is disputing the balance or says they already paid. "
                "Document the dispute and let them know the billing team will review it."
            ),
            checklist=[
                "Express understanding and empathy. Let the patient know you will document "
                "their concern and have the billing team review it within 2 to 3 business days.",
                guava.Field(
                    key="dispute_reason",
                    description="Patient's stated reason for disputing or indicating the balance was already paid.",
                    field_type="text",
                    required=False,
                ),
                guava.Say(
                    "We've noted your dispute and will follow up within 2 to 3 business days. "
                    "We appreciate your patience."
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Stage 4C — Payment plan
    # ------------------------------------------------------------------

    def _handle_payment_plan(self):
        self.set_task(
            objective=(
                "The patient is interested in a payment plan. Note their interest and "
                "schedule a billing team follow-up."
            ),
            checklist=[
                guava.Say(
                    "We do offer payment plans. Let me note your interest and have our billing "
                    "team contact you with options that work for your situation."
                ),
                guava.Field(
                    key="preferred_contact_time",
                    description="Ask the patient for their preferred time for the billing team to call back.",
                    field_type="text",
                    required=False,
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Stage 4D — Callback request
    # ------------------------------------------------------------------

    def _handle_callback_request(self):
        self.set_task(
            objective="The patient would like a callback from the billing team at a better time.",
            checklist=[
                guava.Field(
                    key="preferred_contact_time",
                    description="Ask the patient for the best time for the billing team to reach them.",
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="preferred_callback_number",
                    description="Ask if this is the best number to reach them, or if they prefer a different one.",
                    field_type="text",
                    required=False,
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # End Call
    # ------------------------------------------------------------------

    def end_call(self):
        self.hangup(final_instructions="Close the call warmly and professionally.")

    # ------------------------------------------------------------------
    # Session Done
    # ------------------------------------------------------------------

    @override
    def on_session_done(self):
        result = {
            "call_id": self._call_id,
            "timestamp": datetime.now().isoformat(),
            "patient_name": self._patient_name,
            "balance_amount": self._balance_amount,
            "dos": self._dos,
            "patient_response": self.get_field("patient_response"),
            "dispute_reason": self.get_field("dispute_reason"),
            "payment_confirmation_number": self.get_field("payment_confirmation_number"),
            "preferred_contact_time": self.get_field("preferred_contact_time"),
            "preferred_callback_number": self.get_field("preferred_callback_number"),
            "escalation_callback_time": self.get_field("escalation_callback_time"),
            "estate_contact_name": self.get_field("estate_contact_name"),
            "estate_contact_number": self.get_field("estate_contact_number"),
        }

        # ✅ Final log with full result
        log_call({
            "call_id": self._call_id,
            "type": "patient_ar",
            "status": "completed",
            "event": "session_done",
            "result": result,
            "completed_at": datetime.now().isoformat()
        })

        logging.info(
            "Patient AR follow-up complete — response: %s",
            self.get_field("patient_response"),
        )

    # ------------------------------------------------------------------
    # No answer — HIPAA-compliant voicemail
    # ------------------------------------------------------------------

    def leave_voicemail(self):
        # ✅ Log voicemail
        log_call({
            "call_id": self._call_id,
            "status": "voicemail",
            "event": "left_voicemail",
            "event_time": datetime.now().isoformat()
        })

        self.read_script(
            f"Hello, this is a message for {self._patient_name}. This is {AGENT_NAME} calling from "
            f"{self._provider_name}'s billing office. Please return our call at {CALLBACK_NUMBER} "
            "at your earliest convenience. Thank you."
        )
        self.hangup()

    # ------------------------------------------------------------------
    # Intent routing — sensitive situations
    # ------------------------------------------------------------------

    @override
    def on_intent(self, intent: str) -> None:
        choice = self.intent_classifier.classify(intent)

        if choice == "hostile_or_legal":
            # ✅ Log escalation
            log_call({
                "call_id": self._call_id,
                "event": "escalation_hostile_or_legal",
                "event_time": datetime.now().isoformat()
            })

            self.set_task(
                objective=(
                    "The patient is upset or hostile. De-escalate with empathy and offer "
                    "to have a human billing specialist call them back."
                ),
                checklist=[
                    "Apologize sincerely for the stress and let the patient know their feelings are valid. "
                    "Offer to have a human billing specialist call them back directly.",
                    guava.Field(
                        key="escalation_callback_time",
                        description="Ask for a good time for a billing specialist to reach them.",
                        field_type="text",
                        required=False,
                    ),
                ],
                on_complete=lambda: self.hangup(
                    final_instructions=(
                        "Thank the patient for their patience. Let them know a billing specialist "
                        "will follow up. End the call calmly and professionally."
                    )
                ),
            )

        elif choice == "deceased_patient":
            # ✅ Log deceased patient
            log_call({
                "call_id": self._call_id,
                "event": "deceased_patient_reported",
                "event_time": datetime.now().isoformat()
            })

            self.set_task(
                objective=(
                    "The caller has indicated the patient is deceased. Express condolences "
                    "and offer to note estate contact information for the billing team."
                ),
                checklist=[
                    "Express sincere condolences for their loss.",
                    guava.Field(
                        key="estate_contact_name",
                        description="If the caller offers to provide an estate contact name, collect it.",
                        field_type="text",
                        required=False,
                    ),
                    guava.Field(
                        key="estate_contact_number",
                        description="If they offer a contact number for the estate, collect it.",
                        field_type="text",
                        required=False,
                    ),
                ],
                on_complete=lambda: self.hangup(
                    final_instructions=(
                        "Express condolences once more and let them know the billing team will "
                        "follow up with any estate correspondence. End the call gently."
                    )
                ),
            )


# ---------------------------------------
# API Endpoint: Start by Scenario
# ---------------------------------------
@router.post("/start/scenario")
def start_patient_ar_by_scenario(scenario: str, phone: str):
    """
    Mimics CLI run_demo.py behavior.
    Pass scenario = 'a', 'b', or 'c' and phone number.
    """
    try:
        if scenario not in PATIENT_AR_SCENARIOS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scenario. Valid options: {list(PATIENT_AR_SCENARIOS.keys())}"
            )

        call_id = str(uuid.uuid4())
        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        if not agent_number:
            raise HTTPException(status_code=500, detail="GUAVA_AGENT_NUMBER not set")

        sc = PATIENT_AR_SCENARIOS[scenario]
        kwargs = sc["kwargs"]

        logging.info(f"Starting patient AR call | Scenario: {scenario} | Phone: {phone}")

        # ✅ Initial log entry
        log_call({
            "call_id": call_id,
            "type": "patient_ar",
            "scenario": scenario,
            "label": sc["label"],
            "from": agent_number,
            "to": phone,
            "patient_name": kwargs["patient_name"],
            "status": "initiated",
            "event": "call_initiated",
        })

        # ✅ Trigger call
        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=PatientARFollowUpController(
                patient_name=kwargs["patient_name"],
                call_id=call_id
            ),
        )

        return {
            "message": "Patient AR call started",
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
def start_patient_ar(payload: dict):
    """
    Start patient AR follow-up call with custom patient data.
    """
    try:
        call_id = str(uuid.uuid4())

        phone = payload.get("phone")
        patient_name = payload.get("patient_name")
        provider_name = payload.get("provider_name", PROVIDER_NAME)
        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        if not phone:
            raise HTTPException(status_code=400, detail="Phone required")

        if not patient_name:
            raise HTTPException(status_code=400, detail="Patient name required")

        if not agent_number:
            raise HTTPException(status_code=500, detail="GUAVA_AGENT_NUMBER not set")

        # ✅ Initial log entry
        log_call({
            "call_id": call_id,
            "type": "patient_ar",
            "from": agent_number,
            "to": phone,
            "patient_name": patient_name,
            "provider_name": provider_name,
            "status": "initiated",
            "event": "call_initiated",
        })

        # ✅ Trigger call
        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=PatientARFollowUpController(
                patient_name=patient_name,
                call_id=call_id,
                provider_name=provider_name
            ),
        )

        return {
            "message": "Patient AR call started",
            "call_id": call_id,
            "patient_name": patient_name
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Call failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------
# Get All Patient AR Calls
# ---------------------------------------
@router.get("/calls")
def get_patient_ar_calls():
    try:
        if not os.path.exists(CALLS_FILE):
            return []

        with open(CALLS_FILE, "r") as f:
            calls = json.load(f)

        # ✅ Filter only patient AR calls
        return [c for c in calls if c.get("type") == "patient_ar"]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
