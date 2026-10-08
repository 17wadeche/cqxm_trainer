"""Route governing sections by their headings, never by fixed PDF page numbers.

These are retrieval hints, not policy rules. The selected revision's original
text supplies every requirement, condition and exception.
"""
import re

from record_sections import Section, page_groups


# Each check gets its governing process and applicable appendix before lexical
# search. Additional documents/sections remain available through the tools.
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


def headings(page):
    """Exclude TOCs, references inside prose, and multi-column step rows."""
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
                    # A boundary page belongs to both sections. This preserves
                    # the preceding table's continuation before the new heading.
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
            for docid,patterns in FOCUS.get(check[0],{}).items():
                for section in self.sections:
                    if by_id[section.source_id].document_id==docid and any(re.search(p,section.title,re.I) for p in patterns):
                        if section not in selected:selected.append(section)
        return selected

    def definition_pages(self,checks,sources):
        # Include complete original pages, not an isolated definition cell.
        check_ids={c[0] for c in checks}
        terms=[]
        if check_ids & {'timing','reportability','consultation'}:terms+=['Aware Date','Serious Injury','Working Day']
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
