"""
Sarva Health — Denial Resolution Controller
============================================
Outbound call to a payer's appeals or provider services line to dispute a
denied claim, understand the denial root cause, and initiate an appeal or
obtain correction guidance.

DEMO SCENARIOS
  Branch A — CO-97 bundling denial
    Rep explains which code was bundled; suggests corrected claim with modifier -59.

  Branch B — PR-27 eligibility denial
    Rep confirms coverage was terminated on DOS; agent flags for eligibility re-run.

Usage:
  python users/sarvahealth/denial_resolution.py <payer_phone> \\
    --provider-name "Sarva Health Medical Group" \\
    --claim-number "CLM-2026-00489" \\
    --member-id "BCBS9876543" \\
    --denial-date "2026-02-28" \\
    --denial-code "CO-97"
"""

import guava
import os
import sys
import json
import logging
import argparse
from datetime import datetime
from typing_extensions import override
from guava.helpers.openai import DocumentQA, IntentRecognizer

sys.path.insert(0, os.path.dirname(__file__))
from settings import ORGANIZATION_NAME, AGENT_NAME, PROVIDER_NAME, PROVIDER_NPI

logging.basicConfig(level=logging.INFO)
logging.getLogger('guava').setLevel(logging.INFO)

# Load denial code reference document for on_question handling
_DENIAL_CODES_PATH = os.path.join(os.path.dirname(__file__), "denial_codes.md")
with open(_DENIAL_CODES_PATH) as _f:
    _DENIAL_CODES_DOCUMENT = _f.read()


class DenialResolutionController(guava.CallController):
    """
    Outbound denial resolution call to payer appeals department.

    Flow:
      __init__ → reach_person(on_success=verify_and_identify_denial, on_failure=handle_no_answer)
        → verify_and_identify_denial: provide denial context (NPI, claim, denial code)
        → collect_denial_details: collect denial explanation + resolution path
        → log_denial_outcome (branches on resolution_path)

    on_question: Uses DocumentQA loaded with denial code reference to answer
                 payer questions about specific codes (CO-97, PR-27, etc.)
    """

    def __init__(
        self,
        claim_number: str,
        member_id: str,
        denial_date: str,
        denial_code: str,
        provider_name: str = PROVIDER_NAME,
    ):
        super().__init__()
        self.claim_number = claim_number
        self.member_id = member_id
        self.denial_date = denial_date
        self.denial_code = denial_code
        self.provider_name = provider_name

        self.denial_code_qa = DocumentQA(
            "sarva-denial-codes-reference",
            _DENIAL_CODES_DOCUMENT,
        )
        self.intent_classifier = IntentRecognizer({
            "authorization_request": (
                "Representative is requesting written authorization or a letter of authorization "
                "before they can proceed."
            ),
            "wrong_department": (
                "Representative indicates this is the wrong number or wrong department for this inquiry."
            ),
            "other": "Any other intent not covered above.",
        })

        self.set_persona(
            organization_name=ORGANIZATION_NAME,
            agent_name=AGENT_NAME,
            agent_purpose=(
                "You are calling on behalf of a healthcare provider's billing team to dispute "
                "a denied claim and understand options for resolution or appeal."
            ),
        )

        self.add_info("Provider Name", provider_name)
        self.add_info("Provider NPI", PROVIDER_NPI)
        self.add_info("Claim Number", claim_number)
        self.add_info("Patient Member ID", member_id)
        self.add_info("Denial Date", denial_date)
        self.add_info("Denial Code", denial_code)

        self.reach_person(
            contact_full_name="Provider Appeals Representative",
            on_success=self.verify_and_identify_denial,
            on_failure=self.handle_no_answer,
        )

    # ------------------------------------------------------------------
    # Stage 2 — Provide denial context
    # ------------------------------------------------------------------

    def verify_and_identify_denial(self):
        logging.info("Stage: identifying denied claim — claim: %s, code: %s", self.claim_number, self.denial_code)
        self.set_task(
            objective=(
                "You've reached a provider appeals representative. Introduce yourself, "
                "provide the NPI, and identify the denied claim."
            ),
            checklist=[
                "Provide the provider NPI, then the claim number, patient member ID, denial date, and denial code to the representative as they ask for each. Allow them time to locate the claim.",
                "If the representative asks clarifying questions about the service or clinical context, answer from the available billing information. If you don't have the detail, let them know the billing team can provide it upon callback.",
            ],
            on_complete=self.collect_denial_details,
        )

    # ------------------------------------------------------------------
    # Stage 3 — Collect denial details and resolution path
    # ------------------------------------------------------------------

    def collect_denial_details(self):
        logging.info("Stage: collecting denial details and resolution path")
        self.set_task(
            objective=(
                "Collect a full explanation of the denial and what resolution path "
                "the representative recommends."
            ),
            checklist=[
                guava.Field(
                    key="denial_code_confirmed",
                    description="Ask the representative to confirm the denial code on their end.",
                    field_type="text",
                    required=True,
                ),
                guava.Field(
                    key="denial_reason_full",
                    description="Ask for a full explanation of the denial reason as the representative describes it.",
                    field_type="text",
                    required=True,
                ),
                guava.Field(
                    key="resolution_path",
                    description="Ask what the representative recommends as the best resolution path.",
                    field_type="multiple_choice",
                    choices=[
                        "file_formal_appeal",
                        "submit_corrected_claim",
                        "provide_additional_docs",
                        "no_appeal_available",
                        "escalate_to_supervisor",
                    ],
                    required=True,
                ),
                guava.Field(
                    key="appeal_deadline",
                    description="If an appeal is possible, ask for the deadline to file it.",
                    field_type="date",
                    required=False,
                ),
                guava.Field(
                    key="appeal_fax_or_portal",
                    description="Ask for the fax number or portal URL to submit the appeal or corrected claim.",
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="rep_reference_number",
                    description="Ask for a reference number for this call.",
                    field_type="text",
                    required=False,
                ),
            ],
            on_complete=self.end_call,
        )

    # ------------------------------------------------------------------
    # Termination — branch on resolution path
    # ------------------------------------------------------------------

    def end_call(self):
        path = self.get_field("resolution_path")
        logging.info("Resolution path: %s — %s", path, "requesting supervisor" if path == "escalate_to_supervisor" else "closing")
        if path == "escalate_to_supervisor":
            self._request_supervisor()
        elif path == "no_appeal_available":
            self.hangup(
                final_instructions=(
                    "Thank the representative for the information. Let them know you've noted "
                    "that no appeal is available and will update the billing team. "
                    "End the call professionally."
                )
            )
        else:
            self.hangup(
                final_instructions=(
                    "Thank the representative for their assistance and the guidance on next steps. "
                    "Confirm you have the resolution path and any relevant deadlines on file. "
                    "End the call professionally."
                )
            )

    def _request_supervisor(self):
        logging.info("Stage: supervisor escalation — requesting transfer to senior appeals specialist")
        self.set_task(
            objective=(
                "The representative has suggested escalating to a supervisor. "
                "Request to speak with a supervisor or senior appeals specialist.\n\n"
                "RULES:\n"
                "- Politely ask to be transferred to a supervisor or senior appeals specialist.\n"
                "- If transferred to a supervisor: briefly re-state the claim number and denial code, "
                "then attempt to collect a resolution path and any relevant appeal details.\n"
                "- If no supervisor is available: collect a direct callback number and the best time "
                "to reach the supervisor or appeals team, then close professionally.\n"
                "- Do not re-ask questions already answered by the original representative."
            ),
            checklist=[
                "Ask to be transferred to a supervisor or senior appeals specialist.",
                guava.Field(
                    key="supervisor_resolution_path",
                    description=(
                        "If a supervisor comes on: ask what resolution they can offer. "
                        "Options: file_formal_appeal, submit_corrected_claim, "
                        "provide_additional_docs, no_appeal_available."
                    ),
                    field_type="multiple_choice",
                    choices=[
                        "file_formal_appeal",
                        "submit_corrected_claim",
                        "provide_additional_docs",
                        "no_appeal_available",
                    ],
                    required=False,
                ),
                guava.Field(
                    key="supervisor_appeal_deadline",
                    description="If the supervisor offers an appeal path: ask for the deadline to file.",
                    field_type="date",
                    required=False,
                ),
                guava.Field(
                    key="supervisor_callback_number",
                    description="If no supervisor is available: ask for a direct callback number.",
                    field_type="text",
                    required=False,
                ),
                guava.Field(
                    key="supervisor_callback_time",
                    description="If no supervisor is available: ask for the best callback time.",
                    field_type="text",
                    required=False,
                ),
            ],
            on_complete=lambda: self.hangup(
                final_instructions=(
                    "Thank whoever you spoke with. If the supervisor provided a resolution path, "
                    "confirm next steps and any deadlines. If a callback was scheduled, confirm "
                    "the billing team will follow up. End the call professionally."
                )
            ),
        )

    @override
    def on_session_done(self):
        result = {
            "timestamp": datetime.now().isoformat(),
            "claim_number": self.claim_number,
            "member_id": self.member_id,
            "denial_date": self.denial_date,
            "denial_code_submitted": self.denial_code,
            "denial_code_confirmed": self.get_field("denial_code_confirmed"),
            "denial_reason_full": self.get_field("denial_reason_full"),
            "resolution_path": self.get_field("resolution_path"),
            "appeal_deadline": self.get_field("appeal_deadline"),
            "appeal_fax_or_portal": self.get_field("appeal_fax_or_portal"),
            "rep_reference_number": self.get_field("rep_reference_number"),
            "supervisor_resolution_path": self.get_field("supervisor_resolution_path"),
            "supervisor_appeal_deadline": self.get_field("supervisor_appeal_deadline"),
            "supervisor_callback_number": self.get_field("supervisor_callback_number"),
            "supervisor_callback_time": self.get_field("supervisor_callback_time"),
        }
        print(json.dumps(result, indent=2))
        logging.info("Denial resolution complete — resolution path: %s", self.get_field("resolution_path"))

    def handle_no_answer(self):
        self.hangup(
            final_instructions=(
                f"We were unable to reach a provider appeals representative. "
                f"Leave a brief professional voicemail on behalf of {self.provider_name} "
                f"requesting a callback regarding denied claim {self.claim_number} "
                f"(denial code {self.denial_code}). Provide a callback number."
            )
        )

    # ------------------------------------------------------------------
    # on_question — Answer denial code questions using DocumentQA
    # ------------------------------------------------------------------

    @override
    def on_question(self, question: str) -> str:
        return self.denial_code_qa.ask(question)

    @override
    def on_intent(self, intent: str) -> None:
        choice = self.intent_classifier.classify(intent)
        if choice == "authorization_request":
            self.send_instruction(
                "The representative is requesting written authorization. "
                "Politely let them know that the billing team will send the required authorization "
                "and ask for the fax number or portal to submit it."
            )
        elif choice == "wrong_department":
            self.hangup(
                final_instructions=(
                    "Apologize for the confusion, thank them for their time, and end the call politely."
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sarva Health — Outbound denial resolution call to payer appeals."
    )
    parser.add_argument("phone", help="Payer appeals department phone number to call")
    parser.add_argument("--claim-number", required=True, help="Denied claim number")
    parser.add_argument("--member-id", required=True, help="Patient insurance member ID")
    parser.add_argument("--denial-date", required=True, help="Date of denial (YYYY-MM-DD)")
    parser.add_argument("--denial-code", required=True, help="Denial code received (e.g. CO-97)")
    parser.add_argument("--provider-name", default=PROVIDER_NAME, help="Provider practice name")
    args = parser.parse_args()

    logging.info(
        "Initiating denial resolution call to %s — claim: %s, code: %s",
        args.phone, args.claim_number, args.denial_code,
    )

    guava.Client().create_outbound(
        from_number=os.environ["GUAVA_AGENT_NUMBER"],
        to_number=args.phone,
        call_controller=DenialResolutionController(
            claim_number=args.claim_number,
            member_id=args.member_id,
            denial_date=args.denial_date,
            denial_code=args.denial_code,
            provider_name=args.provider_name,
        ),
    )
