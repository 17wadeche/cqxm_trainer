import re
from models import Citation, Finding
NOT_REPORTABLE_EXCLUSIONS = {
    'manual_fdm', 'manual_fdr', 'manual_fdc', 'manual_img',
    'mdr_narratives', 'mdr_patient_device', 'mdr_initial_reporter',
    'manual_mdr_coding', 'mdr_event_dates', 'mdr_patient_severity',
}
FER_CHECK_IDS = {'brazil_reporting', 'china_reporting', 'japan_reporting', 'korea_reporting'}
_STATE = r'(not[ -]+reportable|non[ -]*reportable|reportable)'
_LABEL = r'(?:(?:(?:US(?:\s+FDA)?|FDA|MDR)\s+)?(?:reportability(?:\s+(?:decision|status|result))?|reporting\s+decision)|MDR\s+Decision)'
_FIELD = re.compile(rf'^{_LABEL}\s*(?:[:=|]\s*)?{_STATE}\s*[.;]?$', re.I)
_LABEL_ONLY = re.compile(rf'^{_LABEL}\s*[:=|]?$', re.I)
_VALUE = re.compile(rf'^{_STATE}\s*[.;]?$', re.I)
_TYPE = re.compile(r'^Decision\s+Type\s*[:=|]?\s*(.+)$', re.I)
_DECISION = re.compile(rf'^Decision(?:\s+(?:Result|Outcome))?\s*[:=|]?\s*{_STATE}\s*[.;]?$', re.I)
_US_ROW = re.compile(rf'^Decision\s+Type\s*[:=|]?\s*US(?:\s+FDA)?\s*[|:]?\s+Decision\s*[:=|]?\s*{_STATE}\s*[.;]?$', re.I)
_US = re.compile(r'^(?:US(?:\s+FDA)?|FDA|United States)$', re.I)
_DECISION_LABEL = re.compile(r'^Decision(?:\s+(?:Result|Outcome))?\s*[:=|]?$', re.I)
def _decision_rows(source):
    row_key, parts, refs = None, [], []
    for chunk in source.chunks:
        table_row = re.match(r'^(.*?, table \d+, row \d+), cell \d+', chunk.locator)
        key = table_row[1] if table_row else None
        if parts and (key is None or key != row_key):
            yield ' | '.join(parts), refs
            parts, refs = [], []
        for raw in chunk.text.splitlines():
            if not raw.strip():
                continue
            ref = Citation(source_id=source.id, chunk_id=chunk.id, quote=raw.strip()[:700])
            if key is None:
                yield raw, [ref]
            else:
                parts.append(raw.strip())
                refs.append(ref)
        row_key = key
    if parts:
        yield ' | '.join(parts), refs
def not_reportable_evidence(sources):
    decisions = []
    for source in sources:
        if source.kind != 'record' or source.document_id not in {'DER', 'PESR'}:
            continue
        pending = us_decision = foreign_decision = pending_type = False
        decision_column = type_column = None
        reportability_section = False
        for raw, refs in _decision_rows(source):
            raw = raw.translate(str.maketrans({'–': '-', '—': '-', '‑': '-', '−': '-'}))
            cells = [' '.join(cell.split()) for cell in re.split(r'\s*[|\t]\s*| {2,}', raw.strip()) if cell.strip()]
            line = ' '.join(' '.join(cells).split())
            if re.fullmatch(r'Reportability(?: Decision)? Summary', line, re.I):
                reportability_section = True
                pending = us_decision = foreign_decision = pending_type = False
                decision_column = type_column = None
                continue
            if re.fullmatch(r'.+ Summary', line, re.I):
                reportability_section = False
                pending = us_decision = foreign_decision = pending_type = False
                decision_column = type_column = None
                continue
            headers = [cell.lower().rstrip(':') for cell in cells]
            if ('decision type' in headers and 'decision' in headers
                and not any(_VALUE.fullmatch(cell) for cell in cells)):
                type_column = headers.index('decision type')
                decision_column = headers.index('decision')
                pending = pending_type = False
                continue
            if type_column is not None and len(cells) > max(type_column, decision_column):
                state = _VALUE.fullmatch(cells[decision_column])
                if state:
                    if _US.fullmatch(cells[type_column]):
                        decisions.append((state[1].lower() != 'reportable', refs))
                    continue
            candidates = [' '.join(cells[:end]) for end in range(len(cells), 0, -1)]
            row = next((m for value in candidates if (m := _US_ROW.fullmatch(value))), None)
            if re.fullmatch(r'Decision\s+Type\s*[:=|]?', line, re.I):
                pending_type, pending = True, False
                continue
            decision_type = None
            if row is None:
                decision_type = next((m for value in candidates
                                      if (m := _TYPE.fullmatch(value)) and _US.fullmatch(m[1])), None)
                decision_type = decision_type or _TYPE.fullmatch(line)
            if decision_type or pending_type:
                value = decision_type[1] if decision_type else line
                us_decision = bool(_US.fullmatch(value))
                foreign_decision = not us_decision
                pending_type = pending = False
                continue
            match = row
            if match is None and not foreign_decision:
                match = next((m for value in candidates if (m := _FIELD.fullmatch(value))), None)
            if match is None and pending:
                match = _VALUE.fullmatch(cells[0])
            if match is None and (us_decision or (reportability_section and not foreign_decision)):
                match = next((m for value in candidates if (m := _DECISION.fullmatch(value))), None)
            if match:
                decisions.append((match[1].lower() != 'reportable', refs))
            pending = bool((not foreign_decision and _LABEL_ONLY.fullmatch(line)) or
                           ((us_decision or (reportability_section and not foreign_decision)) and
                            _DECISION_LABEL.fullmatch(line)))
    if not decisions or not all(negative for negative, _ in decisions):
        return []
    return list({(ref.source_id, ref.chunk_id, ref.quote): ref
                 for _, refs in decisions for ref in refs}.values())
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