"""
Sarva Health — Payer AR Follow-Up Controller
=============================================
Outbound call to a payer's accounts payable or claims payment department to
follow up on an outstanding AR balance — a claim that has aged past the
expected payment window without an ERA/835 received.

DEMO SCENARIOS
  Branch A — Payment issued by check
    Rep confirms check was mailed; provides check number and mail date.
    Flag for lockbox team.

  Branch B — Claim on hold (W-9 update required)
    Rep explains hold reason; collects expected release date.
    Log for provider enrollment team.

Usage:
  python users/sarvahealth/payer_ar_followup.py <payer_phone> \\
    --provider-name "Sarva Health Medical Group" \\
    --claim-number "CLM-2026-00312" \\
    --billed-amount "2450.00" \\
    --dos "2025-11-14" \\
    --submission-date "2025-11-20" \\
    --aging-days 112
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
from settings import ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME, PROVIDER_NPI, TAX_ID

logging.basicConfig(level=logging.INFO)
logging.getLogger('guava').setLevel(logging.INFO)


class PayerARFollowUpController(guava.CallController):
    """
    Outbound AR follow-up call to payer claims payment department.

    Flow:
      __init__ → reach_person(on_success=provide_provider_and_claim_info, on_failure=handle_no_answer)
        → provide_provider_and_claim_info: NPI + Tax ID, then claim number / billed amount / aging as rep asks
        → collect_payment_status: collect status, payment details, hold info
        → log_ar_outcome (branches on payment_status)
    """

    def __init__(
        self,
        claim_number: str,
        billed_amount: str,
        dos: str,
        submission_date: str,
        aging_days: int,
        provider_name: str = PROVIDER_NAME,
    ):
        super().__init__()
        self.claim_number = claim_number
        self.billed_amount = billed_amount
        self.dos = dos
        self.submission_date = submission_date
        self.aging_days = aging_days
        self.provider_name = provider_name
        self._transfer_count = 0

        self.intent_classifier = IntentRecognizer({
            "transfer_or_hold": (
                "Representative is placing the call on hold or transferring to another department."
            ),
            "callback_request": (
                "Representative is requesting a callback or asking the caller to call back later."
            ),
            "other": "Any other intent not covered above.",
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose=(
                "You are calling on behalf of a healthcare provider's billing department to follow up "
                "on an outstanding accounts receivable balance for a claim that has not yet been paid."
            ),
        )

        self.add_info("Provider Name", provider_name)
        self.add_info("Provider NPI", PROVIDER_NPI)
        self.add_info("Provider Tax ID", TAX_ID)
        self.add_info("Claim Number", claim_number)
        self.add_info("Billed Amount", f"${billed_amount}")
        self.add_info("Date of Service", dos)
        self.add_info("Claim Submission Date", submission_date)
        self.add_info("Claim Age", f"{aging_days} days")

        self.reach_person(
            contact_full_name="Claims Payment Representative",
            on_success=self.provide_provider_and_claim_info,
            on_failure=self.handle_no_answer,
        )

    # ------------------------------------------------------------------
    # Stage 2 — Provide all identifying information
    # ------------------------------------------------------------------

    def provide_provider_and_claim_info(self):
        logging.info("Stage: providing provider/claim info — claim: %s, aged %d days", self.claim_number, self.aging_days)
        self.set_task(
            objective=(
                "You've reached a claims payment representative. Provide the provider NPI "
                "and Tax ID to verify the account, then provide the claim number, billed amount, "
                "date of service, and submission date as the representative asks for each. "
                "Reps may ask for these in any order — surface each piece when prompted. "
                "Mention that the claim has aged significantly to convey urgency."
            ),
            checklist=[
                "Provide the provider NPI and Tax ID when the representative asks for account verification.",
                "Provide the claim number, billed amount, date of service, and submission date when the representative is ready. Allow them time to pull up the claim.",
            ],
            on_complete=self.collect_payment_status,
        )

    # ------------------------------------------------------------------
    # Stage 3 — Collect payment status
    # ------------------------------------------------------------------

    def collect_payment_status(self):
        logging.info("Stage: collecting payment status from payer")
        self.set_task(
            objective=(
                "Collect the payment status for this claim and any relevant payment details "
                "or hold information."
            ),
            checklist=[
                guava.Field(
                    key="payment_status",
                    description="What is the current payment status for this claim?",
                    field_type="multiple_choice",
                    choices=["paid_eft", "paid_check", "on_hold", "in_process", "denied", "not_found"],
                    required=True,
                ),
                guava.Field(
                    key="payment_amount",
                    description="If payment has been issued, ask for the amount paid.",
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="payment_date",
                    description="If payment was issued, ask for the date it was issued.",
                    field_type="date",
                    required=False,
                ),
                guava.Field(
                    key="check_or_eft_number",
                    description="Ask for the check number or EFT trace number, if applicable.",
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="hold_reason",
                    description="If the payment is on hold, ask for the reason.",
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="expected_release_date",
                    description="If on hold, ask for the expected payment release date.",
                    field_type="date",
                    required=False,
                ),
                guava.Field(
                    key="rep_name",
                    description="Ask for the representative's name or employee ID for the call record.",
                    field_type="text",
                    required=False,
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Termination — branch on payment status
    # ------------------------------------------------------------------

    def end_call(self):
        status = self.get_field("payment_status")
        logging.info("Payment status: %s — %s", status, "requesting appeals info" if status == "denied" else "collecting rep info for escalation" if status == "not_found" else "closing")
        if status == "denied":
            self.set_task(
                objective=(
                    "The claim has been denied. Collect the appeals department contact "
                    "information before closing."
                ),
                checklist=[
                    guava.Field(
                        key="appeals_department_number",
                        description="Ask if there is a direct appeals department phone number or fax for submitting an appeal.",
                        field_type="text",
                        required=False,
                    ),
                ],
                on_complete=lambda: self.hangup(
                    final_instructions=(
                        "Thank the representative. Let them know the billing team will review "
                        "the denial and may follow up regarding an appeal. End the call professionally."
                    )
                ),
            )
        elif status == "not_found":
            self.set_task(
                objective=(
                    "The claim was not found. Collect rep details for escalation and "
                    "note for resubmission investigation."
                ),
                checklist=[
                    guava.Field(
                        key="rep_employee_id",
                        description="Ask for the representative's employee ID or reference for this call.",
                        field_type="text",
                        required=False,
                    ),
                ],
                on_complete=lambda: self.hangup(
                    final_instructions=(
                        "Thank the representative. Let them know the billing team will investigate "
                        "and follow up. End the call professionally."
                    )
                ),
            )
        else:
            self.hangup(
                final_instructions=(
                    "Thank the representative for the payment status information. "
                    "Confirm you have all the details you need. End the call professionally."
                )
            )

    @override
    def on_session_done(self):
        result = {
            "timestamp": datetime.now().isoformat(),
            "claim_number": self.claim_number,
            "billed_amount": self.billed_amount,
            "dos": self.dos,
            "aging_days": self.aging_days,
            "payment_status": self.get_field("payment_status"),
            "payment_amount": self.get_field("payment_amount"),
            "payment_date": self.get_field("payment_date"),
            "check_or_eft_number": self.get_field("check_or_eft_number"),
            "hold_reason": self.get_field("hold_reason"),
            "expected_release_date": self.get_field("expected_release_date"),
            "rep_name": self.get_field("rep_name"),
            "rep_employee_id": self.get_field("rep_employee_id"),
            "appeals_department_number": self.get_field("appeals_department_number"),
            "payer_callback_number": self.get_field("payer_callback_number"),
            "payer_callback_time": self.get_field("payer_callback_time"),
        }
        print(json.dumps(result, indent=2))
        logging.info("Payer AR follow-up complete — payment status: %s", self.get_field("payment_status"))

    def handle_no_answer(self):
        self.hangup(
            final_instructions=(
                f"We were unable to reach a claims payment representative. "
                f"Leave a brief professional voicemail on behalf of {self.provider_name} "
                f"requesting a callback regarding claim {self.claim_number} payment status. "
                "Provide a callback number."
            )
        )

    @override
    def on_intent(self, intent: str) -> None:
        choice = self.intent_classifier.classify(intent)
        if choice == "transfer_or_hold":
            self._transfer_count += 1
            if self._transfer_count >= 3:
                logging.warning("Transfer limit reached — logging as escalation required.")
                self.hangup(
                    final_instructions=(
                        "We've been transferred multiple times without resolution. "
                        "Politely let the representative know the billing team will escalate "
                        "this matter and follow up in writing. Thank them and end the call."
                    )
                )
        elif choice == "callback_request":
            self.set_task(
                objective="The representative has requested a callback. Collect the callback details.",
                checklist=[
                    guava.Field(
                        key="payer_callback_number",
                        description="Ask for the direct callback number and extension.",
                        field_type="text",
                        required=False,
                    ),
                    guava.Field(
                        key="payer_callback_time",
                        description="Ask for the best time to call back.",
                        field_type="text",
                        required=False,
                    ),
                ],
                on_complete=lambda: self.hangup(
                    final_instructions=(
                        "Thank the representative. Let them know the billing team will call "
                        "back at the time provided. End the call professionally."
                    )
                ),
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sarva Health — Outbound payer AR follow-up call."
    )
    parser.add_argument("phone", help="Payer claims payment department phone number")
    parser.add_argument("--claim-number", required=True, help="Claim number to follow up on")
    parser.add_argument("--billed-amount", required=True, help="Billed amount (e.g. 2450.00)")
    parser.add_argument("--dos", required=True, help="Date of service (YYYY-MM-DD)")
    parser.add_argument("--submission-date", required=True, help="Claim submission date (YYYY-MM-DD)")
    parser.add_argument("--aging-days", type=int, required=True, help="Number of days the claim has aged")
    parser.add_argument("--provider-name", default=PROVIDER_NAME, help="Provider practice name")
    args = parser.parse_args()

    logging.info(
        "Initiating payer AR follow-up call to %s — claim: %s, aged %d days",
        args.phone, args.claim_number, args.aging_days,
    )

    guava.Client().create_outbound(
        from_number=os.environ["GUAVA_AGENT_NUMBER"],
        to_number=args.phone,
        call_controller=PayerARFollowUpController(
            claim_number=args.claim_number,
            billed_amount=args.billed_amount,
            dos=args.dos,
            submission_date=args.submission_date,
            aging_days=args.aging_days,
            provider_name=args.provider_name,
        ),
    )
