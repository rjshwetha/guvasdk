"""
Sarva Health — Appointment Reminder Controller
===============================================
Outbound call to a patient reminding them of an upcoming appointment and
confirming their attendance. Routes reschedule and cancellation requests
to the scheduling team.

DEMO SCENARIOS
  Branch A — Patient confirms
    "Yes, I'll be there." → Log confirmed, close warmly.

  Branch B — Patient needs to reschedule
    "Can we do Thursday instead?" → Collect preferences, log for scheduling team.

  Branch C — Patient wants to cancel
    Acknowledge cancellation, collect reason if offered, log.

Usage:
  python users/sarvahealth/appointment_reminder.py <patient_phone> \\
    --patient-name "David Reyes" \\
    --provider-name "Sarva Health Medical Group" \\
    --appointment-date "Monday, March 16th" \\
    --appointment-time "2:30 PM" \\
    --provider-on-appt "Dr. Patel" \\
    --location "Sarva Health — Main Campus, Suite 204" \\
    --office-number "555-867-5309"
"""

import guava
import os
import sys
import json
import logging
import argparse
from datetime import datetime
from typing_extensions import override
from guava.helpers.openai import IntentRecognizer

sys.path.insert(0, os.path.dirname(__file__))
from settings import ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME, CALLBACK_NUMBER

logging.basicConfig(level=logging.INFO)
logging.getLogger('guava').setLevel(logging.INFO)


class AppointmentReminderController(guava.CallController):
    """
    Outbound appointment reminder call to a patient.

    Flow:
      __init__ → reach_person(on_success=confirm_appointment, on_failure=leave_reminder_voicemail)
        → confirm_appointment: present appointment details, collect appointment_response
        → route_by_response:
            confirmed → log_and_close (confirmed)
            reschedule → collect preferences → log_and_close (reschedule)
            cancel → collect reason → log_and_close (cancel)
            already_cancelled | no_response → log_and_close
    """

    def __init__(
        self,
        patient_name: str,
        provider_name: str,
        appointment_date: str,
        appointment_time: str,
        provider_on_appt: str,
        location: str,
        office_number: str = CALLBACK_NUMBER,
    ):
        super().__init__()
        self._patient_name = patient_name
        self._provider_name = provider_name
        self._appointment_date = appointment_date
        self._appointment_time = appointment_time
        self._provider_on_appt = provider_on_appt
        self._location = location
        self._office_number = office_number

        self.intent_classifier = IntentRecognizer({
            "prep_question": (
                "Patient is asking about appointment preparation, logistics, what to bring, "
                "or anything specific they need to know before the visit."
            ),
            "other": "Any other intent not covered above.",
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose=(
                "You are calling a patient to remind them of their upcoming appointment "
                "and confirm their attendance."
            ),
        )

        self.add_info("Appointment Date", appointment_date)
        self.add_info("Appointment Time", appointment_time)
        self.add_info("Appointment Provider", provider_on_appt)
        self.add_info("Appointment Location", location)
        self.add_info("Office Number", office_number)

        self.reach_person(
            contact_full_name=self._patient_name,
            on_success=self.confirm_appointment,
            on_failure=self.leave_reminder_voicemail,
        )

    # ------------------------------------------------------------------
    # Stage 2 — Confirm attendance
    # ------------------------------------------------------------------

    def confirm_appointment(self):
        logging.info("Stage: confirming appointment — %s on %s at %s", self._patient_name, self._appointment_date, self._appointment_time)
        self.set_task(
            objective=(
                f"You've reached {self._patient_name}. Remind them of their upcoming appointment "
                "and confirm whether they will attend, need to reschedule, or want to cancel."
            ),
            checklist=[
                guava.Say(
                    f"I'm calling to confirm your appointment on {self._appointment_date} "
                    f"at {self._appointment_time} with {self._provider_on_appt} "
                    f"at {self._location}. Does that still work for you?"
                ),
                guava.Field(
                    key="appointment_response",
                    description="What is the patient's response to the appointment confirmation?",
                    field_type="multiple_choice",
                    choices=["confirmed", "reschedule", "cancel", "already_cancelled", "no_response"],
                    required=True,
                ),
            ],
            on_complete=self.route_by_response,
        )

    def route_by_response(self):
        response = self.get_field("appointment_response")
        logging.info("Appointment response: %s", response)

        if response == "confirmed":
            self._handle_confirmed()
        elif response == "reschedule":
            self._handle_reschedule()
        elif response == "cancel":
            self._handle_cancel()
        else:
            # already_cancelled or no_response
            self.end_call()

    # ------------------------------------------------------------------
    # Branch A — Confirmed
    # ------------------------------------------------------------------

    def _handle_confirmed(self):
        self.hangup(
            final_instructions=(
                f"The patient has confirmed their appointment on {self._appointment_date} "
                f"at {self._appointment_time}. Thank them, remind them to call "
                f"{self._office_number} if anything changes, and wish them a great day."
            )
        )

    # ------------------------------------------------------------------
    # Branch B — Reschedule
    # ------------------------------------------------------------------

    def _handle_reschedule(self):
        self.set_task(
            objective=(
                "The patient needs to reschedule. Collect their preferences so the scheduling "
                "team can follow up with a new time."
            ),
            checklist=[
                "Express understanding. Let the patient know the scheduling team will follow up "
                "with available times.",
                guava.Field(
                    key="preferred_reschedule_days",
                    description="Ask the patient for their preferred days or timeframes for rescheduling.",
                    field_type="text",
                    required=False,
                ),
                guava.Say(
                    "I've noted your reschedule request. Our scheduling team will follow up "
                    "with you shortly to confirm a new time. Thank you."
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Branch C — Cancel
    # ------------------------------------------------------------------

    def _handle_cancel(self):
        self.set_task(
            objective=(
                "The patient wants to cancel. Acknowledge the cancellation and collect the "
                "reason if the patient is willing to share."
            ),
            checklist=[
                "Express understanding. Confirm the cancellation and remind the patient that "
                "they can call to reschedule whenever they're ready.",
                guava.Field(
                    key="cancellation_reason",
                    description="Ask for the reason for cancellation, if they are willing to share.",
                    field_type="text",
                    required=False,
                ),
                guava.Say(
                    "We've cancelled your appointment. If you'd like to reschedule in the future, "
                    "please don't hesitate to call us. Have a great day."
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Logging and hangup
    # ------------------------------------------------------------------

    def end_call(self):
        self.hangup(final_instructions="End the call warmly.")

    @override
    def on_session_done(self):
        result = {
            "timestamp": datetime.now().isoformat(),
            "patient_name": self._patient_name,
            "appointment_date": self._appointment_date,
            "appointment_time": self._appointment_time,
            "provider_on_appt": self._provider_on_appt,
            "appointment_response": self.get_field("appointment_response"),
            "preferred_reschedule_days": self.get_field("preferred_reschedule_days"),
            "cancellation_reason": self.get_field("cancellation_reason"),
        }
        print(json.dumps(result, indent=2))
        logging.info(
            "Appointment reminder complete — response: %s",
            self.get_field("appointment_response"),
        )

    # ------------------------------------------------------------------
    # No answer — reminder voicemail
    # ------------------------------------------------------------------

    def leave_reminder_voicemail(self):
        self.read_script(
            f"Hello, this is a message for {self._patient_name}. This is {AGENT_NAME} calling from "
            f"{self._provider_name}. This is a friendly reminder about your appointment on "
            f"{self._appointment_date} at {self._appointment_time} with {self._provider_on_appt}. "
            f"Please call us at {self._office_number} if you need to make any changes. Thank you!"
        )
        self.hangup()

    @override
    def on_intent(self, intent: str) -> None:
        choice = self.intent_classifier.classify(intent)
        if choice == "prep_question":
            self.send_instruction(
                f"The patient has a preparation or logistics question about their appointment. "
                f"Answer what you can based on the appointment context, and direct them to call "
                f"{self._office_number} for anything specific to their visit."
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sarva Health — Outbound appointment reminder call."
    )
    parser.add_argument("phone", help="Patient phone number to call")
    parser.add_argument("--patient-name", required=True, help="Patient full name")
    parser.add_argument("--provider-name", default=PROVIDER_NAME, help="Provider practice name")
    parser.add_argument("--appointment-date", required=True, help="Appointment date (human-readable)")
    parser.add_argument("--appointment-time", required=True, help="Appointment time (e.g. '2:30 PM')")
    parser.add_argument("--provider-on-appt", required=True, help="Provider the patient is seeing")
    parser.add_argument("--location", required=True, help="Appointment location / suite")
    parser.add_argument("--office-number", default=CALLBACK_NUMBER, help="Office callback number")
    args = parser.parse_args()

    logging.info(
        "Initiating appointment reminder call to %s (%s) — %s at %s with %s",
        args.patient_name, args.phone,
        args.appointment_date, args.appointment_time, args.provider_on_appt,
    )

    guava.Client().create_outbound(
        from_number=os.environ["GUAVA_AGENT_NUMBER"],
        to_number=args.phone,
        call_controller=AppointmentReminderController(
            patient_name=args.patient_name,
            provider_name=args.provider_name,
            appointment_date=args.appointment_date,
            appointment_time=args.appointment_time,
            provider_on_appt=args.provider_on_appt,
            location=args.location,
            office_number=args.office_number,
        ),
    )
