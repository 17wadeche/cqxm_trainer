from dataclasses import dataclass
from datetime import date
import re
from models import EvidenceSource, extracted_digest
HEADINGS = {
    'event': 'Event Summary', 'product': 'Product Line Item Summary',
    'analysis': 'Analysis Summary', 'investigation': 'Investigation Summary',
    'reportability': 'Reportability Decision Summary', 'regulatory': 'Regulatory Report Summary',
    'communications': 'Communication Summary', 'tasks': 'Task Summary',
    'acknowledgments': 'EMDR', 'mdr': 'MEDWATCH', 'analysis_detail': 'Product Analysis Report',
}
ROUTES = {
    'intake': ['event','product','investigation'], 'narrative': ['event','investigation','analysis'],
    'identifiers': ['event','product'], 'coding': ['product','analysis'],
    'harm': ['product','reportability','mdr'], 'gfe': ['communications','tasks','product'],
    'investigation': ['investigation','analysis','analysis_detail','tasks'],
    'cause': ['investigation','analysis','analysis_detail','product'],
    'reportability': ['reportability','regulatory','mdr'], 'timing': ['regulatory','acknowledgments','mdr','event'],
    'consultation': ['reportability','investigation','analysis','communications','tasks'],
    'consistency': ['mdr','product','analysis','regulatory','acknowledgments'],
    'closure': ['event','investigation','tasks','analysis','regulatory'],
}
ANCHORS = {
    'intake': [r'Event Description text info',r'Complaint Decision Date'],
    'narrative': [r'Event Description text info',r'As Reported Event description',r'Event Narrative'],
    'identifiers': [r'Full UDI',r'Product Returned to MDT',r'Complaint Decision Date'],
    'coding': [r'PLI Codes',r'Code Type .*ANNEX'],
    'harm': [r'Outcomes Attributed',r'Code Type .*HEALTH IMPACT',r'Patient Symptoms'],
    'gfe': [r'Rationale for No Rtn',r'Reason for No Return',r'Device Status Reason',r'GFE (?:Attempt|Requirement)',r'Successful GFE'],
    'investigation': [r'Summary of Investigation',r'Investigation required'],
    'cause': [r'Summary of Investigation',r'CAUSE NOT ESTABLISHED'],
    'reportability': [r'Decision Type\s+US FDA',r'MDR Decision Tree'],
    'timing': [r'Date Submitted',r'Report Sub Format',r'Message Report Submitted',r'Acknowled?g?e?ment 3'],
    'consultation': [r'Summary of Investigation',r'Decision Type\s+US FDA',r'Medical (?:Judg|Consult)'],
    'consistency': [r'Event Description text info',r'Full UDI',r'Mfr Report #'],
    'closure': [r'Closed Date',r'Completed Date',r'Date Submitted'],
}
@dataclass
class Section:
    id: str
    source_id: str
    kind: str
    title: str
    chunks: list

    def outline(self):
        return {'section_id':self.id,'title':self.title,'first':self.chunks[0].locator,
                'last':self.chunks[-1].locator,'chunks':len(self.chunks)}
def page_groups(source):
    pages={}
    for chunk in source.chunks:
        key=re.sub(r', part \d+$','',chunk.locator)
        pages.setdefault(key,[]).append(chunk)
    return list(pages.values())
class RecordIndex:
    def __init__(self,sources):
        self.sources=[s for s in sources if s.kind=='record']
        self.sections=[]
        for source in sources:
            if source.kind!='record':continue
            current=None
            for page in page_groups(source):
                text='\n'.join(c.text for c in page)
                lines=[' '.join(v.split()) for v in text.splitlines() if v.strip()]
                heading='\n'.join(lines[:24]).lower()
                if source.document_id=='ATTACHMENT':kind='incoming'
                elif source.document_id=='MDR':kind='mdr'
                elif any(re.match(r'^MEDWATCH\b',line,re.I) for line in lines[:12]) and not any(line.lower()=='regulatory report summary' for line in lines[:4]):kind='mdr'
                elif re.search(r'analysis\s+id\s*:',heading):kind='analysis_detail'
                else:
                    kind=next((k for k,v in HEADINGS.items() if v.lower() in [line.lower() for line in lines[:24]]),None)
                    if kind is None:kind=current.kind if current else 'other'
                new_form=kind=='mdr' and bool(re.search(r'A\.\s*PATIENT\s+INFORMATION',text,re.I))
                if current is None or kind!=current.kind or new_form:
                    current=Section(f'section-{len(self.sections)+1:03d}',source.id,kind,source.name if kind=='incoming' else HEADINGS.get(kind,'Other record content'),[])
                    self.sections.append(current)
                current.chunks.extend(page)
    def outline(self,source_id):
        return [s.outline() for s in self.sections if s.source_id==source_id]
    def candidates(self,checks):
        priorities=list(dict.fromkeys(['incoming','event']+[kind for check in checks for kind in ROUTES.get(check[0],[])]))
        return sorted([s for s in self.sections if s.kind in priorities],key=lambda s:priorities.index(s.kind))
    def anchor_pages(self,checks):
        patterns=[p for check in checks for p in ANCHORS.get(check[0],[])]
        derived={(s.file_sha256,c.id) for s in self.sources if s.document_id=='MDR' for c in s.chunks}
        rows=[]
        for source in self.sources:
            for page in page_groups(source):
                text='\n'.join(c.text for c in page)
                if not any(re.search(p,text,re.I) for p in patterns):continue
                for c in page:
                    if source.document_id=='DER' and (source.file_sha256,c.id) in derived:continue
                    rows.append({'source_id':source.id,'chunk_id':c.id,'locator':c.locator,'text':c.text})
        return rows
    def calendar_comparisons(self,sent):
        results=[]
        for source in self.sources:
            if source.document_id not in {'DER','PESR'}:continue
            for page in page_groups(source):
                if not all((source.id,c.id) in sent for c in page):continue
                text='\n'.join(c.text for c in page)
                reports=set(re.findall(r'(?m)^\s*Regulatory Report\s+(\d{6,12})\b',text))
                if len(reports)!=1:continue
                values={label:set(re.findall(re.escape(label)+r'\s+(\d{4}-\d{2}-\d{2})\b',text))
                        for label in ['Aware Date','Date Submitted','Due Date']}
                if any(len(values[label])!=1 for label in ['Aware Date','Date Submitted']):continue
                try:
                    start=next(iter(values['Aware Date']));end=next(iter(values['Date Submitted']))
                    days=(date.fromisoformat(end)-date.fromisoformat(start)).days
                except ValueError:continue
                row={'source_id':source.id,'chunk_ids':[c.id for c in page],'locator':page[0].locator,
                     'regulatory_report_transaction':next(iter(reports)),
                     'start_field':'Aware Date','start':start,'end_field':'Date Submitted','end':end,
                     'calendar_days':days,'method':'end minus start; observed field interval only, no regulatory deadline inferred'}
                if len(values['Due Date'])==1:
                    due=next(iter(values['Due Date']))
                    try:row.update(displayed_due_date=due,calendar_days_before_displayed_due=(date.fromisoformat(due)-date.fromisoformat(end)).days)
                    except ValueError:pass
                results.append(row)
        return results
    def read(self,source_id,section_id,offset=0,limit=12):
        section=next((s for s in self.sections if s.id==section_id and s.source_id==source_id),None)
        if section is None or type(offset)!=int or offset<0 or offset>=len(section.chunks):
            raise ValueError('Unknown section or offset')
        chunks=section.chunks[offset:offset+limit]
        return [{'source_id':source_id,'chunk_id':c.id,'locator':c.locator,'text':c.text} for c in chunks], {
            'section_id':section_id,'offset':offset,'next_offset':offset+len(chunks) if offset+len(chunks)<len(section.chunks) else None}
def embedded_mdrs(source):
    if source.document_id!='DER':return [],[]
    sections=RecordIndex([source]).sections
    linkage='\n'.join(c.text for s in sections if s.kind in {'regulatory','acknowledgments'} for c in s.chunks)
    results,warnings=[],[]
    for section in sections:
        if section.kind!='mdr':continue
        text='\n'.join(c.text for c in section.chunks)
        numbers=set(re.findall(r'\bMfr\s+Report\s*#\s*([A-Za-z0-9-]+)',text,re.I))
        if len(numbers)!=1 or not all(re.search(r'(?<![A-Za-z0-9-])'+re.escape(n)+r'(?![A-Za-z0-9-])',linkage) for n in numbers):
            warnings.append(f'Embedded MedWatch at {section.chunks[0].locator} could not be linked unambiguously to the event; MDR comparison remains limited.')
            continue
        initial=bool(re.search(r'\[\s*[Xx]\s*\]\s*Initial(?!\s+Use)',text))
        follow=bool(re.search(r'\[\s*[Xx]\s*\]\s*Follow[- ]?up',text,re.I))
        role='initial' if initial and not follow else 'follow-up' if follow and not initial else 'unspecified version'
        number=next(iter(numbers))
        results.append(EvidenceSource(id=source.id+'-mdr-'+str(len(results)+1),kind='record',
            name=f'Embedded {role} MDR {number} — {source.name} — {section.chunks[0].locator}',
            document_id='MDR',record_id=source.record_id,revision=None,approved_revision=False,
            file_sha256=source.file_sha256,extracted_text_sha256=extracted_digest(section.chunks),chunks=section.chunks))
        if role=='unspecified version':warnings.append('An embedded MDR version could not be identified from its type-of-report marks; confirm chronology manually.')
    return results,warnings