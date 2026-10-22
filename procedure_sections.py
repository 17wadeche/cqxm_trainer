import re
from record_sections import Section, page_groups
EVENT_DETAILS = [r'^\d+\.\s*Complete Event Details', r'^Appendix [A-Z].*Event Details.*Complaint']
FOCUS = {
    'intake': {'027-P043': [r'^\d+\.\s*Intake'], '027-WI185': [r'^\d+\.\s*(?:Create Record|Complaint Determination)', r'^Appendix [A-Z].*Complaint Assessment']},
    'narrative': {'027-WI185': EVENT_DETAILS},
    'identifiers': {'027-WI185': EVENT_DETAILS},
    'coding': {'027-WI185': [r'^\d+\.\s*Assign Event Coding']},
    'harm': {'027-WI185': [r'^\d+\.\s*Assign Event Coding', r'^Appendix [A-Z].*Event Details.*Complaint']},
    'gfe': {'027-WI188': [r'^\d+\.\s*Follow Up for Additional', r'^Appendix [A-Z].*Good Faith Effort'], '027-WI185': [r'^Appendix [A-Z].*Event Details.*Complaint']},
    'investigation': {'027-WI186': [r'^\d+\.\s*(?:Determine if Complaint|Perform Complaint|Document Complaint|Complete Complaint)', r'^Appendix [A-Z].*(?:Investigation Determination|Technical Assessment Initiation|Rationale for No Further|Investigation Completion)']},
    'cause': {'027-WI186': [r'^\d+\.\s*(?:Perform Complaint|Document Complaint)', r'^Appendix [A-Z].*Rationale for No Further']},
    'reportability': {'054-P044': [r'^\d+\.\s*Make Reportability'], '054-WI198': [r'^\d+\.\s*Make Reportability', r'^Appendix [A-Z].*(?:US Reportability|Reportability Decision Rationale)']},
    'timing': {'054-WI198': [r'^\d+\.\s*Regulatory Reporting', r'^\d+\.\s*Additional Information', r'^Appendix [A-Z].*US Reporting Types'], '054-P044': [r'^Appendix [A-Z].*Aware Date vs']},
    'consultation': {'054-WI198': [r'^\d+\.\s*Make Reportability'], '027-WI186': [r'^\d+\.\s*Perform Complaint']},
    'consistency': {'027-WI185': EVENT_DETAILS+[r'^\d+\.\s*(?:Assign Event Coding|Event Reassessment)']},
    'closure': {'027-P043': [r'^\d+\.\s*(?:Complaint Investigation|Regulatory Reporting|Customer Communication|Complaint Closure)']},
}
for key, base in {
    'initial_reporter':'narrative','country':'narrative',
    'notified_date':'narrative','aware_date':'timing','event_date':'narrative',
    'complaint_notified_date':'narrative','complaint_status':'closure',
    'product_return_status':'gfe','no_return_rationale':'gfe','rfr':'identifiers',
    'brief_description':'narrative','therapy':'identifiers',
    'investigation_summary':'investigation','customer_response':'gfe',
}.items():
    FOCUS[key] = FOCUS[base]
FOCUS['initial_reporter'] = {'027-WI185': EVENT_DETAILS + [r'^Appendix [A-Z].*Regional Privacy Laws']}
FOCUS['complaint_status'] = {
    '027-P043': [r'^\d+\.\s*Intake, Assessment, and Complaint Determination'] + FOCUS['closure']['027-P043'],
    '027-WI185': [r'^\d+\.\s*Complaint Determination', r'^Appendix [A-Z].*Complaint Assessment'],
}
for key in ['notified_date', 'aware_date']:
    FOCUS[key] = {'027-WI185': EVENT_DETAILS,
                  '054-P044': [r'^Appendix [A-Z].*Aware Date vs']}
for key, docid in [('brazil_reporting','D00780668'), ('china_reporting','054-WI204'),
                   ('japan_reporting','D00780698'), ('korea_reporting','D00780699')]:
    FOCUS[key] = {docid: [r'.*'], '054-P044': [r'.*']}
MDR_FIELDS = {
    'mdr_narratives': r'^(?:B[567]|H11):',
    'mdr_patient_device': r'^(?:A[1-9]?|D[0-9]+[ab]?|H[345789]|G[125])(?=\s|:)',
    'mdr_initial_reporter': r'^(?:E[0-9]*|G2):',
    'mdr_event_dates': r'^(?:B[34]|G3):',
    'mdr_patient_severity': r'^(?:B[12]|G7|H[12])(?=\s|:)',
}
for key, fields in MDR_FIELDS.items():
    FOCUS[key] = {'027-WI185': [fields, r'^Overview and processing considerations']}
    if key in {'mdr_narratives','mdr_event_dates','mdr_patient_severity'}:
        FOCUS[key]['054-WI198'] = [r'^\d+\.', r'^Appendix']
def headings(page):
    found=[]
    for chunk in page:
        for raw in chunk.text.splitlines():
            line=' '.join(raw.split())
            if len(raw)-len(raw.lstrip())>12 or re.search(r'\.{3,}', line) or re.search(r'\S {3,}\S',raw.strip()):
                continue
            if line=='Terms and Definitions' or re.match(r'^Appendix [A-Z]\s*[–—-]\s*\S',line):
                found.append(line)
            elif re.match(r'^\d+\.\s+[A-Za-z]',line) and len(line)<100:
                found.append(line)
    return list(dict.fromkeys(found))
class ProcedureIndex:
    def __init__(self,sources):
        self.sections=[]
        for source in sources:
            if source.kind!='procedure':continue
            active=[]
            for page in page_groups(source):
                titles=headings(page)
                if titles:
                    for previous in active:previous.chunks.extend(page)
                    active=[]
                    for title in titles:
                        section=Section(f'policy-{len(self.sections)+1:03d}',source.id,'procedure',title,[])
                        self.sections.append(section);active.append(section)
                elif not active:
                    section=Section(f'policy-{len(self.sections)+1:03d}',source.id,'procedure','Document introduction',[])
                    self.sections.append(section);active=[section]
                for section in active:section.chunks.extend(page)
    def outline(self,source_id):
        return [s.outline() for s in self.sections if s.source_id==source_id]
    def candidates(self,checks,sources):
        by_id={s.id:s for s in sources}
        selected=[]
        for check in checks:
            for section in self.sections:
                if by_id[section.source_id].document_id in check[2] and by_id[section.source_id].document_id.startswith('LOCAL-'):
                    if section not in selected:selected.append(section)
            for docid,patterns in FOCUS.get(check[0],{}).items():
                for section in self.sections:
                    if by_id[section.source_id].document_id==docid and any(re.search(p,section.title,re.I) for p in patterns):
                        if section not in selected:selected.append(section)
        return selected
    def definition_pages(self,checks,sources):
        check_ids={c[0] for c in checks}
        terms=[]
        if check_ids & {'timing','reportability','consultation'}:terms+=['Aware Date','Serious Injury','Working Day']
        if 'aware_date' in check_ids:terms+=['Aware Date']
        if 'notified_date' in check_ids:terms+=['Notified Date','Notify Date']
        if 'initial_reporter' in check_ids:terms+=['Initial Reporter','External Contact','Internal Contact']
        if 'complaint_notified_date' in check_ids:terms+=['Complaint Handling Notified Date','Complaint Handling Notify Date']
        if 'complaint_status' in check_ids:terms+=['Complaint']
        if check_ids & {'intake','investigation','cause'}:terms+=['Complaint','Reasonably Known']
        selected=[]
        docs={d for check in checks for d in check[2]}
        for source in sources:
            if source.kind!='procedure' or source.document_id not in docs:continue
            definitions=[s for s in self.sections if s.source_id==source.id and s.title=='Terms and Definitions']
            ids={c.id for s in definitions for c in s.chunks}
            for page in page_groups(source):
                if any(c.id in ids for c in page) and any(re.search(r'(?m)^\s*'+re.escape(term)+r'\s{2,}',c.text,re.I) for term in terms for c in page):
                    selected.extend({'source_id':source.id,'chunk_id':c.id,'locator':c.locator,'text':c.text} for c in page)
        return selected
    def read(self,source_id,section_id,offset=0,limit=12):
        section=next((s for s in self.sections if s.id==section_id and s.source_id==source_id),None)
        if section is None or type(offset)!=int or offset<0 or offset>=len(section.chunks):
            raise ValueError('Unknown procedure section or offset')
        chunks=section.chunks[offset:offset+limit]
        return [{'source_id':source_id,'chunk_id':c.id,'locator':c.locator,'text':c.text} for c in chunks], {
            'section_id':section_id,'offset':offset,'next_offset':offset+len(chunks) if offset+len(chunks)<len(section.chunks) else None}
def coverage(sections,sent):
    return [{**s.outline(),'source_id':s.source_id,'supplied_chunks':sum((s.source_id,c.id) in sent for c in s.chunks),
             'status':'complete' if all((s.source_id,c.id) in sent for c in s.chunks) else 'partial or not yet supplied'} for s in sections]