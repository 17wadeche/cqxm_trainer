"""Review configuration. The native helper optionally protects tokens with DPAPI."""
import os
from pathlib import Path

VERSION = "0.7.0"
ENVIRONMENT = 'production'
PROVIDER = 'openai_responses'
ENDPOINT = 'https://api.gpt.medtronic.com/providers/openai/v1/responses'
ENDPOINTS = {ENVIRONMENT: ENDPOINT}
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_AUTH = "bearer"
SETTINGS_VERSION = 3
PORT = 8765
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = 57 * 1024 * 1024
MAX_ATTACHMENTS = 100
MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024
CAPTURE_SECONDS = 900
CONTEXT_TOKENS = 128000
TARGET_INPUT_TOKENS = 60000
MAX_INPUT_TOKENS = 96000
CONTEXT_HEADROOM = 8192
RETRIEVAL_OUTPUT_TOKENS = 4096
REVIEW_OUTPUT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 16384
MAX_CHECKS_PER_BATCH = 2
MAX_REVIEW_REQUESTS = 80
ROOT = Path(__file__).resolve().parent
BUNDLED_PROCEDURES = ROOT / 'procedures'


def data_directory():
    configured = os.environ.get("GCH_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "GCHCheckMyWork"
    return Path.home() / ".local/share/gch-check-my-work"


PROCEDURES = [
    ("027-P043", "Complaint Handling"),
    ("027-WI185", "Intake, Assessment and Complaint Determination"),
    ("027-WI186", "Complaint Investigation"),
    ("027-WI188", "Customer Communication and Good Faith Effort"),
    ("054-P044", "Regulatory Reporting"),
    ("054-WI198", "US MDR Reportability and Reporting"),
]

# Topic prompts are not procedure rules. All rules must come from uploaded sources.
GROUPS = [
    {"name": "Intake and coding", "checks": [
        ("intake", "Event intake and complaint determination", ["027-P043", "027-WI185"], False),
        ("narrative", "Event narrative quality and objectivity", ["027-WI185"], False),
        ("identifiers", "Product identifiers and event details", ["027-WI185"], False),
        ("coding", "Event coding and reported allegations", ["027-WI185"], False),
        ("harm", "Harm coding and patient impact consistency", ["027-WI185"], False),
    ]},
    {"name": "Communication", "checks": [
        ("gfe", "Good faith effort and communication documentation", ["027-WI188", "027-WI185"], False),
    ]},
    {"name": "Investigation", "checks": [
        ("investigation", "Investigation decision and further action rationale", ["027-WI186"], False),
        ("cause", "Cause determination and conclusion consistency", ["027-WI186"], False),
    ]},
    {"name": "US MDR", "checks": [
        ("reportability", "US reportability decision and rationale", ["054-P044", "054-WI198"], False),
        ("timing", "US MDR reporting dates and timing", ["054-WI198", "054-P044"], False),
        ("consultation", "Medical judgment consultation documentation", ["054-WI198", "027-WI186"], False),
    ]},
    {"name": "Consistency and closure", "checks": [
        ("consistency", "Consistency between the event record and MDR versions", ["027-WI185"], True),
        ("closure", "Closure sequencing for the recorded stage", ["027-P043"], False),
    ]},
]
