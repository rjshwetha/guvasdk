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

router = APIRouter(prefix="/appointment", tags=["Appointment"])

CALLS_FILE = "calls.json"


# ------------------ Logging ------------------

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


# ------------------ Controller ------------------

class AppointmentReminderController(guava.CallController):

    def __init__(
        self,
        patient_name,
        provider_name,
        appointment_date,
        appointment_time,
        provider_on_appt,
        location,
        office_number,
        call_id
    ):
        super().__init__()

        self.call_id = call_id
        self._patient_name = patient_name
        self._provider_name = provider_name
        self._appointment_date = appointment_date
        self._appointment_time = appointment_time
        self._provider_on_appt = provider_on_appt
        self._location = location
        self._office_number = office_number

        self.intent_classifier = IntentRecognizer({
            "prep_question": "Patient asking about preparation",
            "other": "Other"
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose="Reminder + confirmation call"
        )

        self.add_info("Appointment Date", appointment_date)
        self.add_info("Appointment Time", appointment_time)
        self.add_info("Provider", provider_on_appt)
        self.add_info("Location", location)

        self.reach_person(
            contact_full_name=self._patient_name,
            on_success=self.confirm_appointment,
            on_failure=self.leave_voicemail,
        )

    # ---------- Flow ----------

    def confirm_appointment(self):
        log_call({"call_id": self.call_id, "status": "in_progress"})

        self.set_task(
            objective="Confirm appointment",
            checklist=[
                guava.Say(
                    f"Reminder: appointment on {self._appointment_date} at {self._appointment_time}. Does that work?"
                ),
                guava.Field(
                    key="appointment_response",
                    description="Response",
                    type="multiple_choice",   # ✅ FIXED
                    choices=["confirmed", "reschedule", "cancel"],
                    required=True,
                ),
            ],
            on_complete=self.route_by_response,
        )

    def route_by_response(self):
        response = self.get_field("appointment_response")

        if response == "confirmed":
            self.hangup("Thank you, see you!")

        elif response == "reschedule":
            self.set_task(
                objective="Collect reschedule preference",
                checklist=[
                    guava.Field(
                        key="preferred_days",
                        description="Preferred days",
                        type="text",   # ✅ FIXED
                    )
                ],
                on_complete=self.end_call,
            )

        elif response == "cancel":
            self.set_task(
                objective="Collect cancellation reason",
                checklist=[
                    guava.Field(
                        key="cancel_reason",
                        description="Reason",
                        type="text",   # ✅ FIXED
                    )
                ],
                on_complete=self.end_call,
            )

    def end_call(self):
        self.hangup("Thank you")

    def leave_voicemail(self):
        self.read_script(
            f"Reminder for your appointment on {self._appointment_date} at {self._appointment_time}."
        )
        self.hangup()

    @override
    def on_session_done(self):
        result = {
            "call_id": self.call_id,
            "status": "completed",
            "response": self.get_field("appointment_response"),
            "reschedule": self.get_field("preferred_days"),
            "cancel_reason": self.get_field("cancel_reason"),
        }

        log_call({
            "call_id": self.call_id,
            "type": "appointment",
            "status": "completed",
            "result": result
        })


# ------------------ API ------------------

@router.post("/start")
def start_appointment_call(payload: dict):
    try:
        call_id = str(uuid.uuid4())

        phone = payload.get("phone")
        if not phone:
            raise HTTPException(status_code=400, detail="Phone required")

        if not phone.startswith("+"):
            phone = "+" + phone

        api_key = os.getenv("GUAVA_API_KEY")
        agent_number = os.getenv("GUAVA_AGENT_NUMBER")

        if not api_key or not agent_number:
            raise HTTPException(status_code=500, detail="Missing config")

        log_call({
            "call_id": call_id,
            "type": "appointment",
            "to": phone,
            "status": "initiated"
        })

        guava.Client(api_key=api_key).create_outbound(
            from_number=agent_number,
            to_number=phone,
            call_controller=AppointmentReminderController(
                patient_name=payload.get("patient_name"),
                provider_name=payload.get("provider_name"),
                appointment_date=payload.get("appointment_date"),
                appointment_time=payload.get("appointment_time"),
                provider_on_appt=payload.get("provider_on_appt"),
                location=payload.get("location"),
                office_number=payload.get("office_number") or CALLBACK_NUMBER,
                call_id=call_id
            ),
        )

        return {"call_id": call_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))