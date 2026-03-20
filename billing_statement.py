"""
Sarva Health — Billing Statement Controller
============================================
Outbound call to a patient to notify them of a new billing statement, explain
their balance, and route them to payment or support. This is a proactive
first-touch notification on a new statement — NOT a collections call.

HIPAA NOTE
  Identity is verified before any balance or insurance details are shared.
  Voicemail includes only name, practice name, and portal/callback number.

DEMO SCENARIOS
  Branch A — Patient confused about the bill
    "I thought insurance covered this?" → Aria answers billing FAQ, logs question for team.

  Branch B — Ready to pay online
    "How do I pay?" → Aria provides portal URL and closes.

  Branch C — Wants to speak to billing
    Transfer or schedule callback with billing team.

Usage:
  python users/sarvahealth/billing_statement.py <patient_phone> \\
    --patient-name "Carol Washington" \\
    --provider-name "Sarva Health Medical Group" \\
    --patient-dob "1965-09-04" \\
    --member-id "UHC5551234" \\
    --balance "218.50" \\
    --dos "2026-02-03" \\
    --insurance-paid "654.00"
"""

import guava
import os
import sys
import json
import logging
import argparse
from datetime import datetime
from typing_extensions import override
from guava.helpers.openai import DocumentQA

sys.path.insert(0, os.path.dirname(__file__))
from settings import (
    ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME,
    CALLBACK_NUMBER, PATIENT_PORTAL_URL, TRANSFER_NUMBER,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger('guava').setLevel(logging.INFO)

# Load billing FAQ document for on_question handling
_BILLING_FAQ_PATH = os.path.join(os.path.dirname(__file__), "billing_faq.md")
with open(_BILLING_FAQ_PATH) as _f:
    _BILLING_FAQ_DOCUMENT = _f.read()


class BillingStatementController(guava.CallController):
    """
    Outbound billing statement notification call with HIPAA identity gate.

    Flow:
      __init__ → reach_person(on_success=verify_identity, on_failure=leave_statement_voicemail)
        → verify_identity: collect DOB + member_id → check_identity_match
        → check_identity_match: validate → deliver_statement or identity_mismatch
        → deliver_statement: present statement summary, collect patient_intent
        → route_by_intent (branches on what the patient wants to do)
        → log_and_close → hangup

    on_question: DocumentQA answers billing/EOB questions live on the call
    """

    def __init__(
        self,
        patient_name: str,
        provider_name: str,
        patient_dob: str,
        member_id: str,
        balance: str,
        dos: str,
        insurance_paid: str,
        portal_url: str = PATIENT_PORTAL_URL,
        callback_number: str = CALLBACK_NUMBER,
    ):
        super().__init__()
        self._patient_name = patient_name
        self._provider_name = provider_name
        self._patient_dob = patient_dob
        self._member_id = member_id
        self._balance = balance
        self._dos = dos
        self._insurance_paid = insurance_paid
        self._portal_url = portal_url
        self._callback_number = callback_number

        self.billing_faq = DocumentQA(
            "sarva-billing-faq",
            _BILLING_FAQ_DOCUMENT,
        )

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose=(
                "You are calling a patient to inform them that a new billing statement has been "
                "generated for services at their healthcare provider. "
                "You are helpful, clear, and non-pressuring."
            ),
        )

        # Provider-level info only — no patient account data until identity is verified.
        self.add_info("Billing Office", provider_name)
        self.add_info("Patient Portal URL", portal_url)
        self.add_info("Callback Number", callback_number)

        # HIPAA: greeting must NOT disclose billing purpose before identity is verified.
        # Only ask to speak with the patient by name.
        self.reach_person(
            contact_full_name=self._patient_name,
            greeting=f"Hello, may I speak with {self._patient_name}?",
            on_success=self.verify_identity,
            on_failure=self.leave_statement_voicemail,
        )

    # ------------------------------------------------------------------
    # Stage 2 — HIPAA identity verification
    # ------------------------------------------------------------------

    def verify_identity(self):
        self.set_task(
            objective=(
                f"You've reached someone who may be {self._patient_name}. "
                "Before sharing any account or billing details, verify their identity."
            ),
            checklist=[
                guava.Say(
                    "Before I can share any account details, I need to verify your identity."
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

        if self._identity_matches(dob, identifier):
            logging.info("Identity verified — delivering billing statement to %s", self._patient_name)
            self.deliver_statement()
        else:
            logging.info("Identity mismatch — cannot deliver statement")
            self.identity_mismatch()

    def _identity_matches(self, dob: dict | None, identifier: str | None) -> bool:
        if not dob or not identifier:
            return False
        try:
            provided_dob = f"{dob['year']}-{dob['month']:02d}-{dob['day']:02d}"
        except (KeyError, TypeError):
            provided_dob = str(dob)

        dob_match = provided_dob == self._patient_dob
        id_match = (
            identifier.strip() == self._member_id
            or identifier.strip() == self._member_id[-4:]
        )
        return dob_match and id_match

    def identity_mismatch(self):
        self.set_task(
            objective=(
                "Identity verification failed. Cannot share account details. "
                "Direct the caller to reach billing directly."
            ),
            checklist=[
                "Let the caller know you were unable to verify their identity with the information "
                "provided and that for their security you cannot access account details. "
                f"Provide the billing office number ({self._callback_number}) and encourage them "
                "to call directly or log into the patient portal.",
            ],
            on_complete=lambda: self.hangup(
                final_instructions=(
                    f"Direct the caller to {self._callback_number} or {self._portal_url}. "
                    "End the call politely."
                )
            ),
        )

    # ------------------------------------------------------------------
    # Stage 3 — Deliver statement summary
    # ------------------------------------------------------------------

    def deliver_statement(self):
        # Identity confirmed — now safe to load patient account data into context.
        self.add_info("Statement Balance", self._balance)
        self.add_info("Date of Service", self._dos)
        self.add_info("Insurance Paid", self._insurance_paid)
        self.set_task(
            objective=(
                f"Identity verified. Present {self._patient_name}'s new billing statement "
                "and understand how they'd like to proceed."
            ),
            checklist=[
                guava.Say(
                    f"Thank you. Your new statement shows a patient responsibility balance of "
                    f"{self._balance} for services on {self._dos}. "
                    f"Your insurance paid {self._insurance_paid} toward this claim."
                ),
                guava.Field(
                    key="patient_intent",
                    description="What would the patient like to do?",
                    field_type="multiple_choice",
                    choices=[
                        "pay_online",
                        "pay_by_phone",
                        "speak_to_billing_rep",
                        "dispute_or_question",
                        "request_itemized_bill",
                        "no_action",
                    ],
                    required=True,
                ),
            ],
            on_complete=self.route_by_intent,
        )

    def route_by_intent(self):
        intent = self.get_field("patient_intent")
        logging.info("Patient intent: %s", intent)

        if intent == "pay_online":
            self._handle_pay_online()
        elif intent == "pay_by_phone":
            self._handle_pay_by_phone()
        elif intent == "speak_to_billing_rep":
            self._handle_billing_rep()
        elif intent == "dispute_or_question":
            self._handle_dispute_or_question()
        elif intent == "request_itemized_bill":
            self._handle_itemized_bill()
        else:
            # no_action
            self.end_call()

    # ------------------------------------------------------------------
    # Intent branches
    # ------------------------------------------------------------------

    def _handle_pay_online(self):
        self.set_task(
            objective="Patient wants to pay online. Provide the portal URL and close.",
            checklist=[
                guava.Say(
                    f"You can pay securely through our patient portal at {self._portal_url}. "
                    "Log in with your patient account credentials and navigate to the billing section. "
                    "If you haven't registered, you can create an account using your statement information."
                ),
            ],
            on_complete=self.end_call,
        )

    def _handle_pay_by_phone(self):
        self.set_task(
            objective=(
                "Patient wants to pay by phone. Collect payment confirmation number via "
                "secure DTMF entry (do not collect card numbers verbally)."
            ),
            checklist=[
                "Inform the patient that card payment can be processed securely using their phone keypad. "
                "Do not read card numbers aloud — direct them to enter the card number using the keypad.",
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

    def _handle_billing_rep(self):
        if TRANSFER_NUMBER:
            self.transfer(
                TRANSFER_NUMBER,
                transfer_instructions=(
                    "Let the patient know you're connecting them with a billing team member, "
                    "then transfer when the moment feels natural."
                ),
            )
        else:
            self.set_task(
                objective="Patient wants to speak to billing. No live transfer available — schedule callback.",
                checklist=[
                    guava.Say(
                        f"I'll have a billing team member call you back. They can be reached at "
                        f"{self._callback_number} during business hours as well."
                    ),
                    guava.Field(
                        key="preferred_callback_time",
                        description="Ask the patient for a good time for the billing team to call them back.",
                        field_type="text",
                        required=False,
                    ),
                ],
                on_complete=self.end_call,
            )

    def _handle_dispute_or_question(self):
        self.set_task(
            objective=(
                "Patient has a question or dispute about the bill. Collect their question, "
                "answer it if possible (on_question will handle via DocumentQA), "
                "and log the concern for the billing team."
            ),
            checklist=[
                guava.Field(
                    key="patient_question_or_dispute",
                    description="Ask the patient to describe their question or concern about the bill.",
                    field_type="text",
                    required=False,
                ),
                "Answer the patient's question if you can. Let them know the billing team will "
                "follow up within 2 to 3 business days.",
            ],
            on_complete=self.end_call,
        )

    def _handle_itemized_bill(self):
        self.set_task(
            objective="Patient is requesting an itemized bill. Collect mailing or email preference.",
            checklist=[
                guava.Field(
                    key="itemized_bill_delivery",
                    description="Ask whether the patient would prefer the itemized bill by mail or email.",
                    field_type="multiple_choice",
                    choices=["mail", "email"],
                    required=False,
                ),
                guava.Say(
                    "We'll send your itemized bill to you shortly. If you have any additional "
                    "questions once you receive it, please don't hesitate to call us."
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Logging and hangup
    # ------------------------------------------------------------------

    def end_call(self):
        self.hangup(
            final_instructions=(
                f"End the call kindly. Offer the callback number ({self._callback_number}) "
                "for any future questions."
            )
        )

    @override
    def on_session_done(self):
        result = {
            "timestamp": datetime.now().isoformat(),
            "patient_name": self._patient_name,
            "balance": self._balance,
            "dos": self._dos,
            "patient_intent": self.get_field("patient_intent"),
            "patient_question_or_dispute": self.get_field("patient_question_or_dispute"),
            "payment_confirmation_number": self.get_field("payment_confirmation_number"),
            "preferred_callback_time": self.get_field("preferred_callback_time"),
            "itemized_bill_delivery": self.get_field("itemized_bill_delivery"),
        }
        print(json.dumps(result, indent=2))
        logging.info(
            "Billing statement call complete — patient intent: %s",
            self.get_field("patient_intent"),
        )

    # ------------------------------------------------------------------
    # No answer — HIPAA-compliant voicemail (no balance details)
    # ------------------------------------------------------------------

    def leave_statement_voicemail(self):
        self.read_script(
            f"Hello, this is a message for {self._patient_name}. This is {AGENT_NAME} from "
            f"{self._provider_name}'s billing office. A new billing statement is available on "
            f"your account. Please log in to your patient portal at {self._portal_url} "
            f"or call us at {self._callback_number} if you have questions. Thank you."
        )
        self.hangup()

    # ------------------------------------------------------------------
    # on_question — Answer billing FAQ questions via DocumentQA
    # ------------------------------------------------------------------

    @override
    def on_question(self, question: str) -> str:
        return self.billing_faq.ask(question)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sarva Health — Outbound billing statement notification call."
    )
    parser.add_argument("phone", help="Patient phone number to call")
    parser.add_argument("--patient-name", required=True, help="Patient full name")
    parser.add_argument("--provider-name", default=PROVIDER_NAME, help="Provider practice name")
    parser.add_argument("--patient-dob", required=True, help="Patient date of birth (YYYY-MM-DD)")
    parser.add_argument("--member-id", required=True, help="Patient insurance member ID")
    parser.add_argument("--balance", required=True, help="Patient responsibility balance (e.g. 218.50)")
    parser.add_argument("--dos", required=True, help="Date of service (YYYY-MM-DD)")
    parser.add_argument("--insurance-paid", required=True, help="Amount insurance paid (e.g. 654.00)")
    parser.add_argument("--portal-url", default=PATIENT_PORTAL_URL, help="Patient portal URL")
    parser.add_argument("--callback-number", default=CALLBACK_NUMBER, help="Billing office callback number")
    args = parser.parse_args()

    logging.info(
        "Initiating billing statement call to %s (%s) — balance: $%s",
        args.patient_name, args.phone, args.balance,
    )

    guava.Client().create_outbound(
        from_number=os.environ["GUAVA_AGENT_NUMBER"],
        to_number=args.phone,
        call_controller=BillingStatementController(
            patient_name=args.patient_name,
            provider_name=args.provider_name,
            patient_dob=args.patient_dob,
            member_id=args.member_id,
            balance=args.balance,
            dos=args.dos,
            insurance_paid=args.insurance_paid,
            portal_url=args.portal_url,
            callback_number=args.callback_number,
        ),
    )
