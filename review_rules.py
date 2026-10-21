import re
from models import Citation, Finding
NOT_REPORTABLE_EXCLUSIONS = {
    'manual_fdm', 'manual_fdr', 'manual_fdc', 'manual_img',
    'mdr_narratives', 'mdr_patient_device', 'mdr_initial_reporter',
    'manual_mdr_coding', 'mdr_event_dates', 'mdr_patient_severity',
}
FER_CHECK_IDS = {'brazil_reporting', 'china_reporting', 'japan_reporting', 'korea_reporting'}
_STATE = r'(not[ -]+reportable|non[ -]*reportable|reportable)'
_LABEL = r'(?:(?:(?:US(?:\s+FDA)?|FDA|MDR)\s+)?(?:reportability(?:\s+(?:decision|status))?|reporting\s+decision)|MDR\s+Decision)'
_FIELD = re.compile(rf'^{_LABEL}\s*(?:[:=|]\s*)?{_STATE}\s*[.;]?$', re.I)
_LABEL_ONLY = re.compile(rf'^{_LABEL}\s*[:=|]?$', re.I)
_VALUE = re.compile(rf'^{_STATE}\s*[.;]?$', re.I)
_TYPE = re.compile(r'^Decision\s+Type\s*[:=|]?\s*(.+)$', re.I)
_DECISION = re.compile(rf'^Decision(?:\s+(?:Result|Outcome))?\s*[:=|]?\s*{_STATE}\s*[.;]?$', re.I)
_US_ROW = re.compile(rf'^Decision\s+Type\s*[:=|]?\s*US(?:\s+FDA)?\s*[|:]?\s+Decision\s*[:=|]?\s*{_STATE}\s*[.;]?$', re.I)
def not_reportable_evidence(sources):
    decisions = []
    for source in sources:
        if source.kind != 'record' or source.document_id not in {'DER', 'PESR'}:
            continue
        pending = False
        us_decision = False
        foreign_decision = False
        pending_type = False
        for chunk in source.chunks:
            for raw in chunk.text.splitlines():
                line = ' '.join(raw.split())
                if not line:
                    continue
                row = _US_ROW.fullmatch(line)
                if re.fullmatch(r'Decision\s+Type\s*[:=|]?', line, re.I):
                    pending_type = True
                    pending = False
                    continue
                decision_type = _TYPE.fullmatch(line) if row is None else None
                if decision_type or pending_type:
                    value = decision_type[1] if decision_type else line
                    us_decision = bool(re.fullmatch(r'US(?:\s+FDA)?|FDA|United States', value, re.I))
                    foreign_decision = not us_decision
                    pending_type = False
                    pending = False
                    continue
                match = row or (_FIELD.fullmatch(line) if not foreign_decision else None)
                if match is None and pending:
                    match = _VALUE.fullmatch(line)
                if match is None and us_decision:
                    match = _DECISION.fullmatch(line)
                if match:
                    decisions.append((match[1].lower() != 'reportable', Citation(
                        source_id=source.id, chunk_id=chunk.id, quote=raw.strip())))
                pending = bool((not foreign_decision and _LABEL_ONLY.fullmatch(line)) or
                               (us_decision and re.fullmatch(r'Decision\s*[:=|]?', line, re.I)))
    if not decisions or not all(negative for negative, _ in decisions):
        return []
    return list({(ref.source_id, ref.chunk_id, ref.quote): ref for _, ref in decisions}.values())
def trainer_finding(check):
    return Finding(check_id=check[0], record_element=check[1],
        what_was_done='Trainer Review', record_evidence=[], procedure_references=[],
        assessment='manual_review_needed', feedback='Trainer Review',
        priority='none', study_action='')
def not_reportable_fer(check_id, label, citations):
    return Finding(check_id=check_id, record_element=label,
        what_was_done='The saved event is marked Not Reportable.',
        record_evidence=citations, procedure_references=[], assessment='done_properly',
        feedback='Automatically marked Done Properly because the saved event is Not Reportable.',
        priority='none', study_action='')