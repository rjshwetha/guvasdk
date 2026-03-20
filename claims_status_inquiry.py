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
from settings import ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME, PROVIDER_NPI, TAX_ID

logging.basicConfig(level=logging.INFO)
logging.getLogger('guava').setLevel(logging.INFO)

router = APIRouter(prefix="/claims", tags=["Claims"])

CALLS_FILE = "calls.json"

# ---------------------------------------
# Scenario Registry (Matches run_demo.py)
# ---------------------------------------
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
class ClaimsStatusInquiryController(guava.CallController):
    """
    Outbound claim status inquiry call to payer claims department.

    Flow:
      __init__ → reach_person(on_success=provide_provider_and_claim_info, on_failure=handle_no_answer)
        → provide_provider_and_claim_info: NPI + Tax ID, then claim number / DOS / member ID
        → collect_claim_status: collect status, ETA, denial reason, additional info needed
        → end_call (branches on claim_status)
    """

    def __init__(
        self,
        claim_number: str,
        submission_date: str,
        member_id: str,
        dos: str,
        call_id: str,
        provider_name: str = PROVIDER_NAME,
    ):
        super().__init__()
        self.claim_number = claim_number
        self.submission_date = submission_date
        self.member_id = member_id
        self.dos = dos
        self.call_id = call_id
        self.provider_name = provider_name

        self.intent_classifier = IntentRecognizer({
            "wrong_department": (
                "Representative indicates this is the wrong number or wrong department "
                "for this type of inquiry."
            ),
            "other": "Any other intent not covered above.",
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose=(
                "You are calling on behalf of a healthcare provider's billing department "
                "to check the status of a submitted claim."
            ),
        )

        self.add_info("Provider Name", provider_name)
        self.add_info("Provider NPI", PROVIDER_NPI)
        self.add_info("Provider Tax ID", TAX_ID)
        self.add_info("Claim Number", claim_number)
        self.add_info("Claim Submission Date", submission_date)
        self.add_info("Patient Member ID", member_id)
        self.add_info("Date of Service", dos)

        self.reach_person(
            contact_full_name="Claims Department Representative",
            on_success=self.provide_provider_and_claim_info,
            on_failure=self.handle_no_answer,
        )

    # ------------------------------------------------------------------
    # Stage 2 — Provide all identifying information
    # ------------------------------------------------------------------
    def provide_provider_and_claim_info(self):
        logging.info("Stage: providing provider/claim info — claim: %s", self.claim_number)

        # ✅ Log reached person
        log_call({
            "call_id": self.call_id,
            "status": "in_progress",
            "event": "reached_person",
            "event_time": datetime.now().isoformat()
        })

        self.set_task(
            objective=(
                "You've reached a claims department representative. Provide the provider NPI "
                "and Tax ID to verify the account, then provide the claim number, submission date, "
                "patient member ID, and date of service as the representative asks for each. "
                "Reps may ask for these in any order — surface each piece when prompted."
            ),
            checklist=[
                "Provide the provider NPI and Tax ID when the representative asks for account verification.",
                "Provide the claim number, submission date, patient member ID, and date of service when the representative is ready. Allow them time to locate the claim.",
            ],
            on_complete=self.collect_claim_status,
        )

    # ------------------------------------------------------------------
    # Stage 3 — Collect claim status
    # ------------------------------------------------------------------
    def collect_claim_status(self):
        logging.info("Stage: collecting claim status from payer")

        # ✅ Log info provided
        log_call({
            "call_id": self.call_id,
            "event": "info_provided",
            "event_time": datetime.now().isoformat()
        })

        self.set_task(
            objective=(
                "Collect the current status of the claim from the representative, "
                "along with any relevant payment or denial details."
            ),
            checklist=[
                guava.Field(
                    key="claim_status",
                    description="What is the current status of the claim as reported by the payer?",
                    field_type="multiple_choice",
                    choices=["received_processing", "pending_info", "denied", "paid", "not_found"],
                    required=True,
                ),
                guava.Field(
                    key="expected_payment_date",
                    description="Ask for the expected payment or adjudication date, if the claim is in processing.",
                    field_type="date",
                    required=False,
                ),
                guava.Field(
                    key="payment_amount",
                    description="If paid, ask for the payment amount issued.",
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="denial_reason",
                    description="If denied, ask for the denial reason or code.",
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="additional_info_needed",
                    description="Ask if the payer requires any additional documentation or information.",
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="rep_name",
                    description="Ask for the representative's name or ID for the call record.",
                    field_type="text",
                    required=False,
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Termination — branch on claim status
    # ------------------------------------------------------------------
    def end_call(self):
        status = self.get_field("claim_status")
        logging.info("Claim status: %s", status)

        # ✅ Log claim status collected
        log_call({
            "call_id": self.call_id,
            "event": "claim_status_collected",
            "claim_status": status,
            "expected_payment_date": self.get_field("expected_payment_date"),
            "payment_amount": self.get_field("payment_amount"),
            "denial_reason": self.get_field("denial_reason"),
            "additional_info_needed": self.get_field("additional_info_needed"),
            "rep_name": self.get_field("rep_name"),
            "event_time": datetime.now().isoformat()
        })

        if status == "not_found":
            self.set_task(
                objective=(
                    "The claim was not found. Ask the representative to confirm the correct "
                    "submission channel and any details that would help locate or resubmit it."
                ),
                checklist=[
                    guava.Field(
                        key="submission_channel_guidance",
                        description=(
                            "Ask the representative to confirm the correct electronic or paper "
                            "submission channel for this payer and what information is needed."
                        ),
                        field_type="text",
                        required=False,
                    ),
                ],
                on_complete=lambda: self.hangup(
                    final_instructions=(
                        "Thank the representative for their help. Let them know the billing team "
                        "will investigate and resubmit the claim. End the call professionally."
                    )
                ),
            )
        elif status == "denied":
            self.hangup(
                final_instructions=(
                    "Thank the representative for the denial details. Let them know the billing "
                    "team will review the denial and may follow up regarding an appeal. "
                    "Ask if there is a direct appeals department number before ending the call."
                )
            )
        else:
            self.hangup(
                final_instructions=(
                    "Thank the representative for the status update. "
                    "Confirm you have the information you need. End the call professionally."
                )
            )

    # ------------------------------------------------------------------
    # Session Done
    # ------------------------------------------------------------------
    @override
    def on_session_done(self):
        result = {
            "call_id": self.call_id,
            "timestamp": datetime.now().isoformat(),
            "claim_number": self.claim_number,
            "submission_date": self.submission_date,
            "member_id": self.member_id,
            "dos": self.dos,
            "claim_status": self.get_field("claim_status"),
            "expected_payment_date": self.get_field("expected_payment_date"),
            "payment_amount": self.get_field("payment_amount"),
            "denial_reason": self.get_field("denial_reason"),
            "additional_info_needed": self.get_field("additional_info_needed"),
            "rep_name": self.get_field("rep_name"),
            "submission_channel_guidance": self.get_field("submission_channel_guidance"),
        }

        # ✅ Final log with full result
        log_call({
            "call_id": self.call_id,
            "type": "claims",
            "status": "completed",
            "event": "session_done",
            "result": result,
            "completed_at": datetime.now().isoformat()
        })

        logging.info("Claims status inquiry complete — status: %s", self.get_field("claim_status"))

    # ------------------------------------------------------------------
    # No Answer
    # ------------------------------------------------------------------
    def handle_no_answer(self):
        # ✅ Log no answer
        log_call({
            "call_id": self.call_id,
            "status": "no_answer",
            "event": "no_answer",
            "event_time": datetime.now().isoformat()
        })

        self.hangup(
            final_instructions=(
                f"We were unable to reach a claims department representative. "
                f"Leave a brief professional voicemail on behalf of {self.provider_name} "
                f"requesting a callback to check on claim number {self.claim_number}. "
                "Provide a callback number if available."
            )
        )

    # ------------------------------------------------------------------
    # Intent Handler
    # ------------------------------------------------------------------
    @override
    def on_intent(self, intent: str) -> None:
        choice = self.intent_classifier.classify(intent)
        if choice == "wrong_department":
            # ✅ Log wrong department
            log_call({
                "call_id": self.call_id,
                "status": "failed",
                "event": "wrong_department",
                "event_time": datetime.now().isoformat()
            })
            self.hangup(
                final_instructions=(
                    "Apologize for reaching the wrong department, thank them for their time, "
                    "and end the call politely."
                )
            )


# ---------------------------------------
# API Endpoint: Start by Scenario
# ---------------------------------------
@router.post("/start/scenario")
def start_claim_by_scenario(scenario: str, phone: str):
    """
    Mimics CLI run_demo.py behavior.
    Pass scenario = 'a' or 'b' and phone number.
    """
    try:
        if scenario not in CLAIMS_SCENARIOS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scenario. Valid options: {list(CLAIMS_SCENARIOS.keys())}"
            )

        call_id = str(uuid.uuid4())
        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        if not agent_number:
            raise HTTPException(status_code=500, detail="GUAVA_AGENT_NUMBER not set")

        sc = CLAIMS_SCENARIOS[scenario]
        kwargs = sc["kwargs"]

        logging.info(f"Starting claims call | Scenario: {scenario} | Phone: {phone}")

        # ✅ Initial log entry
        log_call({
            "call_id": call_id,
            "type": "claims",
            "scenario": scenario,
            "label": sc["label"],
            "from": agent_number,
            "to": phone,
            "claim_number": kwargs["claim_number"],
            "submission_date": kwargs["submission_date"],
            "member_id": kwargs["member_id"],
            "dos": kwargs["dos"],
            "status": "initiated",
            "event": "call_initiated",
        })

        # ✅ Trigger call
        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=ClaimsStatusInquiryController(
                claim_number=kwargs["claim_number"],
                submission_date=kwargs["submission_date"],
                member_id=kwargs["member_id"],
                dos=kwargs["dos"],
                call_id=call_id
            ),
        )

        return {
            "message": "Claims call started",
            "call_id": call_id,
            "scenario": scenario,
            "label": sc["label"],
            "claim_number": kwargs["claim_number"]
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
def start_claim(payload: dict):
    """
    Start claims status inquiry with custom claim data.
    """
    try:
        call_id = str(uuid.uuid4())

        phone = payload.get("phone")
        claim_number = payload.get("claim_number")
        submission_date = payload.get("submission_date")
        member_id = payload.get("member_id")
        dos = payload.get("dos")
        provider_name = payload.get("provider_name", PROVIDER_NAME)
        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        if not phone:
            raise HTTPException(status_code=400, detail="Phone required")

        if not claim_number:
            raise HTTPException(status_code=400, detail="Claim number required")

        if not agent_number:
            raise HTTPException(status_code=500, detail="GUAVA_AGENT_NUMBER not set")

        # ✅ Initial log entry
        log_call({
            "call_id": call_id,
            "type": "claims",
            "from": agent_number,
            "to": phone,
            "claim_number": claim_number,
            "submission_date": submission_date,
            "member_id": member_id,
            "dos": dos,
            "provider_name": provider_name,
            "status": "initiated",
            "event": "call_initiated",
        })

        # ✅ Trigger call
        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=ClaimsStatusInquiryController(
                claim_number=claim_number,
                submission_date=submission_date,
                member_id=member_id,
                dos=dos,
                call_id=call_id,
                provider_name=provider_name
            ),
        )

        return {
            "message": "Claims call started",
            "call_id": call_id,
            "claim_number": claim_number
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Call failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------
# Get All Claims Calls
# ---------------------------------------
@router.get("/calls")
def get_claims_calls():
    try:
        if not os.path.exists(CALLS_FILE):
            return []

        with open(CALLS_FILE, "r") as f:
            calls = json.load(f)

        # ✅ Filter only claims calls
        return [c for c in calls if c.get("type") == "claims"]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
