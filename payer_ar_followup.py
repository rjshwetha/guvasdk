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

from payer_ar_followup import PayerARFollowUpController

logging.basicConfig(level=logging.INFO)
logging.getLogger("guava").setLevel(logging.INFO)

router = APIRouter(prefix="/payer-ar", tags=["Payer AR Follow-Up"])

CALLS_FILE = "calls.json"


# -------------------------------
# Logging Utility (same as eligibility)
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
# Extended Controller with call_id tracking
# -------------------------------
class PayerARFollowUpControllerWithTracking(PayerARFollowUpController):

    def __init__(self, *args, call_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.call_id = call_id

    @override
    def on_session_done(self):
        result = {
            "call_id": self.call_id,
            "timestamp": datetime.now().isoformat(),
            "claim_number": self.claim_number,
            "payment_status": self.get_field("payment_status"),
            "payment_amount": self.get_field("payment_amount"),
            "payment_date": self.get_field("payment_date"),
            "hold_reason": self.get_field("hold_reason"),
            "expected_release_date": self.get_field("expected_release_date"),
        }

        log_call({
            "call_id": self.call_id,
            "type": "payer_ar_followup",
            "status": "completed",
            "result": result
        })

        logging.info(
            "Payer AR follow-up completed — call_id: %s, status: %s",
            self.call_id,
            result["payment_status"]
        )


# -------------------------------
# API Endpoint
# -------------------------------
@router.post("/start")
def start_call(payload: dict):
    try:
        call_id = str(uuid.uuid4())

        phone = payload.get("phone")
        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        if not phone:
            raise HTTPException(status_code=400, detail="Phone number is required")

        # Initial log
        log_call({
            "call_id": call_id,
            "type": "payer_ar_followup",
            "to": phone,
            "status": "initiated"
        })

        guava.Client(api_key=os.getenv("GUAVA_API_KEY")).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=PayerARFollowUpControllerWithTracking(
                claim_number=payload.get("claim_number"),
                billed_amount=payload.get("billed_amount"),
                dos=payload.get("dos"),
                submission_date=payload.get("submission_date"),
                aging_days=payload.get("aging_days"),
                provider_name=payload.get("provider_name"),
                call_id=call_id
            ),
        )

        return {
            "message": "Call initiated",
            "call_id": call_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))