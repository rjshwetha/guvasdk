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

router = APIRouter(prefix="/payer-ar", tags=["Payer AR Follow-Up"])

CALLS_FILE = "calls.json"


# -------------------------------
# Logging Utility
# -------------------------------
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


# -------------------------------
# Controller (NO imports from itself)
# -------------------------------
class PayerARFollowUpController(guava.CallController):

    def __init__(
        self,
        claim_number,
        billed_amount,
        dos,
        submission_date,
        aging_days,
        provider_name,
        call_id
    ):
        super().__init__()

        self.claim_number = claim_number
        self.billed_amount = billed_amount
        self.dos = dos
        self.submission_date = submission_date
        self.aging_days = aging_days
        self.provider_name = provider_name
        self.call_id = call_id

        self.intent_classifier = IntentRecognizer({
            "transfer_or_hold": "Rep transferring or putting on hold",
            "callback_request": "Rep asking for callback",
            "other": "Other"
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose="Follow up on unpaid insurance claims"
        )

        self.add_info("Provider Name", provider_name)
        self.add_info("Provider NPI", PROVIDER_NPI)
        self.add_info("Provider Tax ID", TAX_ID)
        self.add_info("Claim Number", claim_number)
        self.add_info("Billed Amount", billed_amount)
        self.add_info("DOS", dos)
        self.add_info("Submission Date", submission_date)
        self.add_info("Aging", f"{aging_days} days")

        self.reach_person(
            contact_full_name="Claims Representative",
            on_success=self.collect_status,
            on_failure=self.handle_no_answer,
        )

    def collect_status(self):
        log_call({
            "call_id": self.call_id,
            "status": "in_progress"
        })

        self.set_task(
            objective="Collect payment status",
            checklist=[
                guava.Field(
                    key="payment_status",
                    description="Payment status",
                    type="multiple_choice",
                    choices=["paid", "on_hold", "denied", "not_found"],
                    required=True
                ),
                guava.Field(
                    key="payment_amount",
                    description="Payment amount",
                    type="text"
                ),
                guava.Field(
                    key="payment_date",
                    description="Payment date",
                    type="text"
                ),
                guava.Field(
                    key="hold_reason",
                    description="Hold reason",
                    type="text"
                ),
            ],
            on_complete=self.end_call
        )

    def end_call(self):
        self.hangup("Thank you for the information")

    @override
    def on_session_done(self):
        result = {
            "call_id": self.call_id,
            "claim_number": self.claim_number,
            "payment_status": self.get_field("payment_status"),
            "payment_amount": self.get_field("payment_amount"),
            "payment_date": self.get_field("payment_date"),
            "hold_reason": self.get_field("hold_reason"),
        }

        log_call({
            "call_id": self.call_id,
            "type": "payer_ar_followup",
            "status": "completed",
            "result": result
        })

    def handle_no_answer(self):
        log_call({
            "call_id": self.call_id,
            "status": "no_answer"
        })
        self.hangup("No answer")


# -------------------------------
# API Endpoint
# -------------------------------
@router.post("/start")
def start_call(payload: dict):
    try:
        call_id = str(uuid.uuid4())
        phone = payload.get("phone")

        if not phone:
            raise HTTPException(status_code=400, detail="Phone is required")

        log_call({
            "call_id": call_id,
            "type": "payer_ar_followup",
            "to": phone,
            "status": "initiated"
        })

        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=os.getenv("GUAVA_AGENT_NUMBER"),
            to_number=phone,
            call_controller=PayerARFollowUpController(
                claim_number=payload.get("claim_number"),
                billed_amount=payload.get("billed_amount"),
                dos=payload.get("dos"),
                submission_date=payload.get("submission_date"),
                aging_days=payload.get("aging_days"),
                provider_name=payload.get("provider_name"),
                call_id=call_id
            ),
        )

        return {"call_id": call_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))