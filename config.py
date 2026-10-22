import os
from pathlib import Path
VERSION = "0.8.0"
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
MAX_CHECKS_PER_BATCH = 5
MAX_REVIEW_REQUESTS = 160
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
    ("D00780668", "Brazil Reporting"),
    ("054-WI204", "China Reporting"),
    ("D00780698", "Japan Reporting"),
    ("D00780699", "South Korea Reporting"),
]
REVIEW_AREAS = [('narrative', 'Event Summary', ['027-WI185'], False),
 ('initial_reporter', 'Initial Reporter', ['027-WI185'], False),
 ('country', 'Country', ['027-WI185'], False),
 ('manual_communication', 'Communication Needed', None, False),
 ('notified_date', 'Notified Date', ['027-WI185', '054-P044'], False),
 ('aware_date', 'Aware Date', ['027-WI185', '054-P044'], False),
 ('event_date', 'Event Date', ['027-WI185'], False),
 ('complaint_notified_date', 'Complaint Handling Notified Date', ['027-WI185'], False),
 ('manual_record_count', 'Correct number of complaint records generated', None, False),
 ('harm', 'Patient outcome', ['027-WI185'], False),
 ('manual_plis', 'PLIs (correct ones and amount)', None, False),
 ('manual_manufacturing_site', 'Manufacturing Site ID', None, False),
 ('complaint_status', 'Complaint Status', ['027-P043', '027-WI185'], False),
 ('identifiers', 'Lot/Serial #', ['027-WI185'], False),
 ('product_return_status', 'Product Return Status', ['027-WI185', '027-WI188'], False),
 ('no_return_rationale', 'Rationale for No Return', ['027-WI188', '027-WI185'], False),
 ('rfr', 'RFR', ['027-WI185'], False),
 ('manual_fdp', 'FDP', None, False),
 ('manual_haz', 'HAZ', None, False),
 ('manual_afc', 'AFC', None, False),
 ('manual_fdm', 'FDM', None, False),
 ('manual_fdr', 'FDR', None, False),
 ('manual_fdc', 'FDC', None, False),
 ('manual_ime', 'IME', None, False),
 ('manual_imf', 'IMF', None, False),
 ('manual_img', 'IMG', None, False),
 ('brief_description', 'Brief Description', ['027-WI185'], False),
 ('therapy', 'Therapy', None, False),
 ('manual_analysis_transaction', 'Product Analysis Transaction', None, False),
 ('reportability', 'Reportability Decision', ['054-P044', '054-WI198'], False),
 ('brazil_reporting', 'Brazil FER & Rationale', ['D00780668', '054-P044'], False),
 ('china_reporting', 'China FER & Rationale', ['054-WI204', '054-P044'], False),
 ('japan_reporting', 'Japan FER & Rationale', ['D00780698', '054-P044'], False),
 ('korea_reporting', 'Korea FER & Rationale', ['D00780699', '054-P044'], False),
 ('mdr_narratives', 'MDR narratives (Sections B5-B7, H11)', [ '054-WI198'], True),
 ('mdr_patient_device',
  'Patient/Device information in MDR (Sections A, D, H3-5, H7-9, G1-2, G5)',
  ['027-WI185'],
  True),
 ('mdr_initial_reporter',
  'Initial Reporter information in MDR (Sections E and G2)',
  ['027-WI185'],
  True),
 ('manual_mdr_coding', 'Coding in MDR (Section H6)', None, False),
 ('mdr_event_dates', 'Event-related dates in MDR (B3, B4, G3)', ['054-WI198'], True),
 ('mdr_patient_severity',
  'Patient severity identified in MDR (Sections B1, B2, G7, H1, H2)',
  ['054-WI198'],
  True),
 ('manual_investigation_determination', 'Investigation determination', None, False),
 ('manual_related_investigation', 'Existing or related investigation reference', None, False),
 ('manual_technical_assessment', 'Technical Assessment/Review', None, False),
 ('manual_no_investigation_rationale', 'Rationale for no formal investigation', None, False),
 ('investigation_summary', 'Investigation Summary', ['027-WI186'], False),
 ('gfe', 'Good Faith Effort', ['027-WI188', '027-WI185'], False),
 ('customer_response', 'Customer response', ['027-WI188'], False)]
MANUAL_CHECK_IDS = {row[0] for row in REVIEW_AREAS if row[2] is None}
REVIEW_LABELS = {row[0]: row[1] for row in REVIEW_AREAS}
GROUPS = [{"name": f"Review areas {start+1}–{min(start+5, len(REVIEW_AREAS))}",
           "checks": [(key, label, docs or [], mdr) for key, label, docs, mdr in REVIEW_AREAS[start:start+5]]}
          for start in range(0, len(REVIEW_AREAS), 5)]