"""
Sarva Health — Shared Settings
================================
All demo configuration lives here. In production these would be loaded
from environment variables or a secrets manager.
"""

import os

# ---------------------------------------------------------------------------
# Shared persona (all controllers use the same Aria identity)
# ---------------------------------------------------------------------------

ORGANIZATION_NAME = "Sarva Health"
AGENT_NAME = "Aria"

# ---------------------------------------------------------------------------
# Provider identity (used by payer-facing controllers)
# ---------------------------------------------------------------------------

PROVIDER_NAME = os.environ.get("PROVIDER_NAME", "Sarva Health Medical Group")
PROVIDER_NPI = os.environ.get("PROVIDER_NPI", "1234567890")
TAX_ID = os.environ.get("TAX_ID", "12-3456789")

# ---------------------------------------------------------------------------
# Contact numbers
# ---------------------------------------------------------------------------

# Number to transfer billing/clinical calls to during business hours
TRANSFER_NUMBER = os.environ.get("TRANSFER_NUMBER", "")

# Callback number read to patients in voicemails / closing instructions
CALLBACK_NUMBER = os.environ.get("CALLBACK_NUMBER", "our office")

# Patient-facing portal URL (used in BillingStatementController voicemail)
PATIENT_PORTAL_URL = os.environ.get("PATIENT_PORTAL_URL", "portal.sarvahealth.com")
