"""
Sarva Health — Patient Satisfaction Controller
===============================================
Outbound call to a patient to conduct a brief post-visit satisfaction survey.
Captures structured feedback for CAHPS-aligned quality metrics.

DEMO SCENARIOS
  Branch A — Happy with visit
    High scores across the board; mentions nurse was great. Aria thanks them warmly.

  Branch B — Mixed feedback
    Long wait time (score 2), liked the doctor (score 5). Aria notes the wait concern
    and flags for patient experience manager.

  Branch C — Declines survey
    Patient too busy. Aria thanks them gracefully and closes.

Usage:
  python users/sarvahealth/patient_satisfaction.py <patient_phone> \\
    --patient-name "Jennifer Park" \\
    --provider-name "Sarva Health Medical Group" \\
    --visit-date "March 4th"
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


class PatientSatisfactionController(guava.CallController):
    """
    Outbound patient satisfaction survey call.

    Flow:
      __init__ → get_contact_on_the_phone (custom two-step: identity + consent in one task)
        → is_respondent_available:
            identity_confirmed + contact_available → conduct_survey
            contact_unavailable / wrong_number / do_not_contact → hangup gracefully
        → conduct_survey: collect 5 ratings + open feedback → log_survey_results

    on_intent:
        opt-out / do not call → acknowledge and hangup
        clinical concern → do NOT address; direct to practice
        low score / complaint → offer patient experience manager callback
        very positive → thank genuinely
    """

    def __init__(
        self,
        patient_name: str,
        provider_name: str,
        visit_date: str,
        patient_number: str = "",
    ):
        super().__init__()
        self._patient_name = patient_name
        self._provider_name = provider_name
        self._visit_date = visit_date
        self._patient_number = patient_number

        self.intent_classifier = IntentRecognizer({
            "opt_out": (
                "Patient wants to be removed from the calling list, opt out of surveys, "
                "or requests not to be called again."
            ),
            "clinical_concern": (
                "Patient is raising a clinical issue — symptoms, pain, medication, "
                "diagnosis, or treatment questions."
            ),
            "dissatisfied": (
                "Patient is expressing strong dissatisfaction, frustration, or a complaint "
                "about their experience."
            ),
            "very_positive": (
                "Patient is expressing enthusiastic praise or very positive feedback "
                "about their experience."
            ),
            "other": "Any other intent not covered above.",
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose=(
                "You are conducting a brief patient satisfaction survey on behalf of the "
                "healthcare practice the patient recently visited. "
                "You are warm, brief, and appreciative of their time."
            ),
        )

        self.get_contact_on_the_phone()

    # ------------------------------------------------------------------
    # Stage 1 — Identity + consent (combined, templatized pattern)
    # ------------------------------------------------------------------

    def get_contact_on_the_phone(self):
        self.set_task(
            objective=(
                f"Reach {self._patient_name} and determine whether they are willing to "
                "participate in a brief patient satisfaction survey. "
                "Do NOT hang up under any circumstances unless it is a wrong number or DNC request. "
                "If the respondent is hesitant, respond with warmth and understanding — never pressure them."
            ),
            checklist=[
                guava.Say(
                    f"Hello, I'm {AGENT_NAME}, a virtual assistant calling on behalf of "
                    f"{self._provider_name}. We're conducting a brief patient satisfaction survey. "
                    f"Am I speaking with {self._patient_name}?"
                ),
                guava.Field(
                    key="contact_identity",
                    description=(
                        f"The outcome of reaching {self._patient_name}. "
                        f"If the person who answered is not {self._patient_name}, ask to speak with them or be transferred.\n"
                        "OPTIONS:\n"
                        f"- 'identity_confirmed': {self._patient_name} is on the phone;\n"
                        f"- 'contact_unavailable': {self._patient_name} cannot be reached right now;\n"
                        "- 'do_not_contact': anyone at this number asks not to be called again;\n"
                        f"- 'wrong_number': {self._patient_name} is not known at this number."
                    ),
                    field_type="multiple_choice",
                    choices=["identity_confirmed", "contact_unavailable", "do_not_contact", "wrong_number"],
                    required=True,
                ),
                guava.Field(
                    key="contact_availability",
                    description=(
                        f"Whether {self._patient_name} is willing to take a brief survey. "
                        f"Only collect after identity is confirmed. "
                        f"If they were not the original respondent, briefly restate your purpose before asking. "
                        f"Let them know we noticed their recent visit on {self._visit_date} and that "
                        "the survey takes about two minutes.\n"
                        "OPTIONS:\n"
                        "- 'contact_available': they agree to participate;\n"
                        "- 'contact_unavailable': they decline or say it's not a good time;\n"
                        "- 'do_not_contact': they ask not to be called again."
                    ),
                    field_type="multiple_choice",
                    choices=["contact_available", "contact_unavailable", "do_not_contact"],
                    required=False,
                ),
            ],
            on_complete=self.is_respondent_available,
        )

    def is_respondent_available(self):
        contact_identity = self.get_field("contact_identity")
        contact_availability = self.get_field("contact_availability")

        logging.info("Contact result — identity: %s, availability: %s", contact_identity, contact_availability)
        if contact_identity == "do_not_contact" or contact_availability == "do_not_contact":
            logging.info("Do-not-contact request recorded for %s.", self._patient_name)
            self.hangup(
                final_instructions=(
                    "Acknowledge their request not to be contacted again. "
                    "Apologize for any inconvenience and wish them a good day."
                )
            )
            return

        if contact_identity == "wrong_number":
            self.hangup(
                final_instructions="Apologize for the confusion and thank them for their time."
            )
            return

        if contact_identity != "identity_confirmed":
            # contact_unavailable — patient couldn't come to the phone
            self.hangup(
                final_instructions=(
                    "Thank whoever answered for their time. "
                    "Do not leave any clinical or personal information. Wish them a good day."
                )
            )
            return

        if contact_availability == "contact_available":
            self.conduct_survey()
        else:
            self.decline_survey()

    # ------------------------------------------------------------------
    # Stage 2 — Survey
    # ------------------------------------------------------------------

    def conduct_survey(self):
        logging.info("Stage: conducting satisfaction survey — %s", self._patient_name)
        self.set_task(
            objective=(
                "The patient has agreed to the survey. Ask each question naturally — "
                "one at a time. Acknowledge their responses warmly between questions."
            ),
            checklist=[
                guava.Say("Great, thank you! I'll ask you just a few quick questions."),
                guava.Field(
                    key="overall_experience",
                    description=(
                        "On a scale of 1 to 5, with 5 being excellent, how would you rate "
                        "your overall experience at the visit?"
                    ),
                    field_type="integer",
                    required=True,
                ),
                guava.Field(
                    key="provider_communication",
                    description=(
                        "How well did your provider explain things to you — did you feel informed "
                        "and heard? Rate from 1 to 5."
                    ),
                    field_type="integer",
                    required=True,
                ),
                guava.Field(
                    key="wait_time_rating",
                    description=(
                        "How would you rate the wait time for your appointment? 1 to 5."
                    ),
                    field_type="integer",
                    required=True,
                ),
                guava.Field(
                    key="staff_friendliness",
                    description=(
                        "How friendly and helpful was the staff during your visit? 1 to 5."
                    ),
                    field_type="integer",
                    required=True,
                ),
                guava.Field(
                    key="open_feedback",
                    description=(
                        "Is there anything specific you'd like to share — something that went "
                        "well or something we could improve?"
                    ),
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="recommend_practice",
                    description=(
                        "And finally — how likely are you to recommend our practice to a friend "
                        "or family member? 1 to 5."
                    ),
                    field_type="integer",
                    required=True,
                ),
                guava.Say(
                    "Thank you so much for your feedback. It really helps us improve. "
                    "We hope to see you again soon!"
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Termination
    # ------------------------------------------------------------------

    def end_call(self):
        self.hangup(final_instructions="End the call warmly and thank the patient genuinely.")

    @override
    def on_session_done(self):
        overall = self.get_field("overall_experience")
        provider_comm = self.get_field("provider_communication")
        wait_time = self.get_field("wait_time_rating")
        staff = self.get_field("staff_friendliness")
        feedback = self.get_field("open_feedback")
        nps_proxy = self.get_field("recommend_practice")

        result = {
            "timestamp": datetime.now().isoformat(),
            "patient_name": self._patient_name,
            "visit_date": self._visit_date,
            "overall_experience": overall,
            "provider_communication": provider_comm,
            "wait_time_rating": wait_time,
            "staff_friendliness": staff,
            "open_feedback": feedback,
            "recommend_practice": nps_proxy,
        }
        print(json.dumps(result, indent=2))

        scores = [s for s in [overall, provider_comm, wait_time, staff, nps_proxy] if s is not None]
        low_score = any(int(s) <= 2 for s in scores if str(s).isdigit())
        if low_score:
            logging.warning(
                "Patient satisfaction — LOW SCORE FLAG: %s — needs patient experience follow-up.",
                self._patient_name,
            )
        else:
            logging.info("Patient satisfaction survey complete — %s.", self._patient_name)

    def decline_survey(self):
        logging.info("Survey declined — %s — closing gracefully", self._patient_name)
        self.set_task(
            objective="The patient declined the survey. Thank them gracefully and close.",
            checklist=[
                "Thank the patient for their time and let them know their feedback is always "
                "welcome. Mention that they can share feedback anytime through the patient portal.",
            ],
            on_complete=lambda: self.hangup(
                final_instructions="Thank the patient and wish them well. End the call warmly."
            ),
        )

    # ------------------------------------------------------------------
    # Intent routing — handle special situations during the survey
    # ------------------------------------------------------------------

    @override
    def on_intent(self, intent: str) -> None:
        choice = self.intent_classifier.classify(intent)

        if choice == "opt_out":
            self.set_task(
                objective=(
                    "Patient wants to opt out of survey calls. Acknowledge, apologize for "
                    "the inconvenience, and log the opt-out."
                ),
                checklist=[
                    "Apologize sincerely for the interruption and let the patient know they've "
                    "been removed from our outreach list.",
                ],
                on_complete=lambda: self.hangup(
                    final_instructions="Thank the patient and end the call respectfully."
                ),
            )

        elif choice == "clinical_concern":
            self.send_instruction(
                "The patient has raised a clinical concern. Do not provide any clinical guidance. "
                f"Express care and advise them to call the practice directly at {CALLBACK_NUMBER} "
                "or contact their provider through the patient portal. "
                "Note the concern for the patient experience team."
            )

        elif choice == "dissatisfied":
            self.set_task(
                objective=(
                    "Patient expressed strong dissatisfaction. Respond with genuine empathy and "
                    "offer to connect them with a patient experience manager."
                ),
                checklist=[
                    "Express sincere empathy for their experience and let them know their feedback "
                    "is taken seriously.",
                    guava.Field(
                        key="wants_experience_manager_callback",
                        description=(
                            "Ask the patient if they would like a patient experience manager "
                            "to call them back personally."
                        ),
                        field_type="multiple_choice",
                        choices=["yes", "no"],
                        required=True,
                    ),
                ],
                on_complete=self._handle_experience_escalation,
            )

        elif choice == "very_positive":
            self.send_instruction(
                "The patient is very enthusiastic and positive. Express genuine gratitude. "
                "Mention that they can refer friends and family and that their kind words "
                "will be shared with the care team."
            )

    def _handle_experience_escalation(self):
        if self.get_field("wants_experience_manager_callback") == "yes":
            logging.warning(
                "PRIORITY ESCALATION: %s — patient experience manager callback requested.",
                self._patient_name,
            )
        self.hangup(
            final_instructions=(
                "Thank the patient for sharing their experience. If they want a callback, "
                "confirm a patient experience manager will follow up within one business day. "
                "End the call warmly."
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sarva Health — Outbound patient satisfaction survey call."
    )
    parser.add_argument("phone", help="Patient phone number to call")
    parser.add_argument("--patient-name", required=True, help="Patient full name")
    parser.add_argument("--provider-name", default=PROVIDER_NAME, help="Provider practice name")
    parser.add_argument("--visit-date", required=True, help="Recent visit date (human-readable, e.g. 'March 4th')")
    args = parser.parse_args()

    logging.info(
        "Initiating patient satisfaction survey call to %s (%s) — visit: %s",
        args.patient_name, args.phone, args.visit_date,
    )

    guava.Client().create_outbound(
        from_number=os.environ["GUAVA_AGENT_NUMBER"],
        to_number=args.phone,
        call_controller=PatientSatisfactionController(
            patient_name=args.patient_name,
            provider_name=args.provider_name,
            visit_date=args.visit_date,
            patient_number=args.phone,
        ),
    )
