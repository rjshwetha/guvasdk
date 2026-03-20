#!/usr/bin/env python3
"""
Sarva Health Demo Launcher
===========================
Run any demo scenario with a single command — no manual CLI args needed.

Usage:
  python users/sarvahealth/run_demo.py list
  python users/sarvahealth/run_demo.py <controller> <a|b|c>
  python users/sarvahealth/run_demo.py <controller> <a|b|c> --phone +14155551234

Phone number:
  Set DEMO_PHONE in your environment, or pass --phone on the command line.
  This is the number the outbound call will be placed to (your test phone).

Examples:
  DEMO_PHONE=+14155551234 python users/sarvahealth/run_demo.py list
  DEMO_PHONE=+14155551234 python users/sarvahealth/run_demo.py denial a
  DEMO_PHONE=+14155551234 python users/sarvahealth/run_demo.py patient_ar b
  python users/sarvahealth/run_demo.py billing a --phone +14155551234
"""

import os
import sys
import argparse
import importlib
import logging
import textwrap

# Ensure the sarvahealth package directory is on the path so we can import
# each controller module directly (mirrors the sys.path.insert each script does).
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------
# Each entry:
#   module  — filename (without .py) of the controller
#   class   — class name inside that module
#   label   — human-readable controller label
#   group   — "patient" or "payer" for display grouping
#   scenarios — dict of letter → {label, kwargs passed to the controller class}
# ---------------------------------------------------------------------------

CONTROLLERS = {

    # ------------------------------------------------------------------ #
    # Patient-Facing                                                       #
    # ------------------------------------------------------------------ #

    "appointment": {
        "module": "appointment_reminder",
        "class": "AppointmentReminderController",
        "label": "Appointment Reminder",
        "group": "patient",
        "scenarios": {
            "a": {
                "label": "Patient confirms attendance",
                "kwargs": {
                    "patient_name": "David Reyes",
                    "provider_name": "Sarva Health Medical Group",
                    "appointment_date": "Monday, March 16th",
                    "appointment_time": "2:30 PM",
                    "provider_on_appt": "Dr. Patel",
                    "location": "Sarva Health — Main Campus, Suite 204",
                },
            },
            "b": {
                "label": "Patient requests reschedule",
                "kwargs": {
                    "patient_name": "Sarah Nguyen",
                    "provider_name": "Sarva Health Medical Group",
                    "appointment_date": "Tuesday, March 17th",
                    "appointment_time": "10:00 AM",
                    "provider_on_appt": "Dr. Rivera",
                    "location": "Sarva Health — North Campus, Suite 110",
                },
            },
            "c": {
                "label": "Patient wants to cancel",
                "kwargs": {
                    "patient_name": "Robert Kim",
                    "provider_name": "Sarva Health Medical Group",
                    "appointment_date": "Wednesday, March 18th",
                    "appointment_time": "3:15 PM",
                    "provider_on_appt": "Dr. Okonkwo",
                    "location": "Sarva Health — Main Campus, Suite 312",
                },
            },
        },
    },

    "satisfaction": {
        "module": "patient_satisfaction",
        "class": "PatientSatisfactionController",
        "label": "Patient Satisfaction Survey",
        "group": "patient",
        "scenarios": {
            "a": {
                "label": "Happy patient — high scores across the board",
                "kwargs": {
                    "patient_name": "Jennifer Park",
                    "provider_name": "Sarva Health Medical Group",
                    "visit_date": "March 4th",
                },
            },
            "b": {
                "label": "Mixed feedback — long wait, liked the doctor",
                "kwargs": {
                    "patient_name": "Michael Torres",
                    "provider_name": "Sarva Health Medical Group",
                    "visit_date": "February 26th",
                },
            },
            "c": {
                "label": "Patient declines the survey",
                "kwargs": {
                    "patient_name": "Lisa Chen",
                    "provider_name": "Sarva Health Medical Group",
                    "visit_date": "March 5th",
                },
            },
        },
    },

    "patient_ar": {
        "module": "patient_ar_followup",
        "class": "PatientARFollowUpController",
        "label": "Patient AR Follow-Up  [HIPAA gate + mock API]",
        "group": "patient",
        "scenarios": {
            "a": {
                "label": "Maria Chen — identity verified, pays by card  ($342.00)",
                "kwargs": {
                    "patient_name": "Maria Chen",
                },
            },
            "b": {
                "label": "James Torres — identity verified, disputes balance  ($189.50)",
                "kwargs": {
                    "patient_name": "James Torres",
                },
            },
            "c": {
                "label": "Sandra Kim — identity verified, requests payment plan  ($775.00)",
                "kwargs": {
                    "patient_name": "Sandra Kim",
                },
            },
        },
    },

    "billing": {
        "module": "billing_statement",
        "class": "BillingStatementController",
        "label": "Billing Statement  [HIPAA gate + DocumentQA]",
        "group": "patient",
        "scenarios": {
            "a": {
                "label": "Carol Washington — confused about bill, asks billing questions  ($218.50)",
                "kwargs": {
                    "patient_name": "Carol Washington",
                    "provider_name": "Sarva Health Medical Group",
                    "patient_dob": "1965-09-04",
                    "member_id": "UHC5551234",
                    "balance": "$218.50",
                    "dos": "February 3rd",
                    "insurance_paid": "$654.00",
                },
            },
            "b": {
                "label": "Robert Ellis — ready to pay online  ($312.75)",
                "kwargs": {
                    "patient_name": "Robert Ellis",
                    "provider_name": "Sarva Health Medical Group",
                    "patient_dob": "1979-02-22",
                    "member_id": "UHC5559876",
                    "balance": "$312.75",
                    "dos": "January 15th",
                    "insurance_paid": "$891.25",
                },
            },
            "c": {
                "label": "Patricia Moore — wants to speak to a billing rep  ($489.00)",
                "kwargs": {
                    "patient_name": "Patricia Moore",
                    "provider_name": "Sarva Health Medical Group",
                    "patient_dob": "1952-06-11",
                    "member_id": "BCBS5554321",
                    "balance": "$489.00",
                    "dos": "February 18th",
                    "insurance_paid": "$1,247.00",
                },
            },
        },
    },

    # ------------------------------------------------------------------ #
    # Payer-Facing                                                         #
    # ------------------------------------------------------------------ #

    "denial": {
        "module": "denial_resolution",
        "class": "DenialResolutionController",
        "label": "Denial Resolution  [DocumentQA for denial codes]",
        "group": "payer",
        "scenarios": {
            "a": {
                "label": "CO-97 bundling denial — modifier -59 resolution path",
                "kwargs": {
                    "claim_number": "CLM-2026-00489",
                    "member_id": "BCBS9876543",
                    "denial_date": "2026-02-28",
                    "denial_code": "CO-97",
                },
            },
            "b": {
                "label": "PR-27 eligibility denial — coverage terminated on DOS",
                "kwargs": {
                    "claim_number": "CLM-2026-00391",
                    "member_id": "UHC4412398",
                    "denial_date": "2026-03-01",
                    "denial_code": "PR-27",
                },
            },
        },
    },

    "payer_ar": {
        "module": "payer_ar_followup",
        "class": "PayerARFollowUpController",
        "label": "Payer AR Follow-Up",
        "group": "payer",
        "scenarios": {
            "a": {
                "label": "Payment issued by check — check number + mail date",
                "kwargs": {
                    "claim_number": "CLM-2026-00312",
                    "billed_amount": "2450.00",
                    "dos": "2025-11-14",
                    "submission_date": "2025-11-20",
                    "aging_days": 112,
                },
            },
            "b": {
                "label": "Claim on hold — W-9 update required, expected release date",
                "kwargs": {
                    "claim_number": "CLM-2026-00156",
                    "billed_amount": "1875.00",
                    "dos": "2025-09-08",
                    "submission_date": "2025-09-15",
                    "aging_days": 177,
                },
            },
        },
    },

    "eligibility": {
        "module": "eligibility_verification",
        "class": "EligibilityVerificationController",
        "label": "Eligibility Verification",
        "group": "payer",
        "scenarios": {
            "a": {
                "label": "Coverage active — deductible remaining + copay confirmed",
                "kwargs": {
                    "patient_name": "Jane Smith",
                    "member_id": "UHC1234567",
                    "patient_dob": "03/15/1978",
                    "dos": "2026-04-15",
                },
            },
            "b": {
                "label": "Coverage termed — termination date and reason collected",
                "kwargs": {
                    "patient_name": "Robert Davis",
                    "member_id": "BCBS7890123",
                    "patient_dob": "08/22/1961",
                    "dos": "2026-04-10",
                },
            },
        },
    },

    "claims": {
        "module": "claims_status_inquiry",
        "class": "ClaimsStatusInquiryController",
        "label": "Claims Status Inquiry",
        "group": "payer",
        "scenarios": {
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
        },
    },
}


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_RULE = "─" * 60

def _print_list():
    print()
    print("  Sarva Health — Demo Scenarios")
    print(f"  {_RULE}")
    print()

    groups = [("patient", "PATIENT-FACING"), ("payer", "PAYER-FACING")]
    for group_key, group_label in groups:
        print(f"  {group_label}")
        for name, cfg in CONTROLLERS.items():
            if cfg["group"] != group_key:
                continue
            print(f"    {name:<14}  {cfg['label']}")
            for letter, sc in cfg["scenarios"].items():
                print(f"      {letter}  {sc['label']}")
        print()

    print("  Run a scenario:")
    print("    DEMO_PHONE=+1... python users/sarvahealth/run_demo.py <controller> <a|b|c>")
    print("    python users/sarvahealth/run_demo.py <controller> <a|b|c> --phone +1...")
    print()


def _print_scenario_summary(controller_name: str, scenario_letter: str, phone: str):
    cfg = CONTROLLERS[controller_name]
    sc = cfg["scenarios"][scenario_letter]
    print()
    print(f"  {_RULE}")
    print(f"  Controller : {cfg['label']}")
    print(f"  Scenario   : {scenario_letter.upper()} — {sc['label']}")
    print(f"  To number  : {phone}")
    print(f"  {_RULE}")
    if sc["kwargs"]:
        print("  Parameters :")
        for k, v in sc["kwargs"].items():
            print(f"    {k:<28} {v}")
    print()


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def _launch(controller_name: str, scenario_letter: str, phone: str):
    import guava

    cfg = CONTROLLERS[controller_name]
    sc = cfg["scenarios"][scenario_letter]

    _print_scenario_summary(controller_name, scenario_letter, phone)

    logging.info(
        "Launching %s / scenario %s → %s",
        controller_name, scenario_letter.upper(), phone,
    )

    mod = importlib.import_module(cfg["module"])
    cls = getattr(mod, cfg["class"])
    controller_instance = cls(**sc["kwargs"])

    agent_number = os.environ.get("GUAVA_AGENT_NUMBER")
    if not agent_number:
        print("ERROR: GUAVA_AGENT_NUMBER environment variable is not set.")
        sys.exit(1)

    guava.Client().create_outbound(
        from_number=agent_number,
        to_number=phone,
        call_controller=controller_instance,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sarva Health demo launcher — run any scenario without typing CLI args.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python users/sarvahealth/run_demo.py list
              DEMO_PHONE=+14155551234 python users/sarvahealth/run_demo.py denial a
              python users/sarvahealth/run_demo.py patient_ar b --phone +14155551234
        """),
    )
    parser.add_argument(
        "controller",
        nargs="?",
        choices=list(CONTROLLERS.keys()) + ["list"],
        help="Controller to run, or 'list' to show all scenarios.",
        metavar="controller|list",
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        help="Scenario letter: a, b, or c.",
    )
    parser.add_argument(
        "--phone",
        default=os.environ.get("DEMO_PHONE"),
        help="Phone number to call. Defaults to $DEMO_PHONE env var.",
    )

    args = parser.parse_args()

    # No args — print list
    if not args.controller or args.controller == "list":
        _print_list()
        return

    controller_name = args.controller

    if not args.scenario:
        # Show scenarios for the selected controller
        cfg = CONTROLLERS[controller_name]
        print()
        print(f"  {cfg['label']}")
        print(f"  {_RULE}")
        for letter, sc in cfg["scenarios"].items():
            print(f"    {letter}  {sc['label']}")
        print()
        print(f"  Usage: python users/sarvahealth/run_demo.py {controller_name} <a|b|c>")
        print()
        return

    scenario_letter = args.scenario.lower()
    cfg = CONTROLLERS[controller_name]

    if scenario_letter not in cfg["scenarios"]:
        valid = ", ".join(cfg["scenarios"].keys())
        print(f"ERROR: Scenario '{scenario_letter}' not found for '{controller_name}'. Valid: {valid}")
        sys.exit(1)

    if not args.phone:
        print("ERROR: No phone number provided.")
        print("  Set DEMO_PHONE environment variable or pass --phone +1...")
        sys.exit(1)

    _launch(controller_name, scenario_letter, args.phone)


if __name__ == "__main__":
    main()
