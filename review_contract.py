"""Model-facing evidence IDs resolve to immutable excerpts owned by this review."""
from copy import copy
import json
import re

from pydantic import Field, ValidationError

from models import Citation, Finding, Review
from mdt import output_schema


class DraftFinding(Finding):
    record_evidence: list[str]
    procedure_references: list[str]


class DraftReview(Review):
    findings: list[DraftFinding] = Field(min_length=1, max_length=60)


class ContractError(ValueError):
    def __init__(self, code, instruction, path='findings'):
        self.issue = {'code':code, 'path':path, 'instruction':instruction}
        super().__init__(instruction)


class EvidenceCatalog:
    def __init__(self, sources, compact=False):
        self.sources = {s.id:s for s in sources}
        self.entries, self.keys = {}, {}
        self.compact=compact

    def preview(self, chunks):
        """Return a staged catalog; only commit it if these excerpts are sent."""
        staged=copy(self)
        staged.entries, staged.keys = self.entries.copy(), self.keys.copy()
        return staged.add(chunks), staged

    def add(self, chunks):
        rows=[]
        for row in chunks:
            source=self.sources.get(row['source_id'])
            chunk=next((c for c in source.chunks if c.id==row['chunk_id']),None) if source else None
            text=row['text']
            if chunk is None or not isinstance(text,str) or not text or text not in chunk.text:
                raise ContractError('input_excerpt_mismatch','Reload the source document; extracted evidence does not match its stored chunk.')
            excerpts=[]
            while text:
                end=min(600,len(text))
                if end<len(text):
                    boundary=text.rfind(' ',0,end)
                    if boundary>=300:end=boundary
                quote=text[:end].strip();text=text[end:]
                if not quote:continue
                key=(source.id,chunk.id,quote)
                evidence_id=self.keys.get(key)
                if evidence_id is None:
                    evidence_id=f'E{len(self.entries)+1:04d}'
                    self.keys[key]=evidence_id
                    self.entries[evidence_id]=(source.kind,Citation(source_id=source.id,chunk_id=chunk.id,quote=quote))
                # Keep the immutable verbatim quote for Word/evidence validation.
                # Model packets need neither PDF indentation nor blank-line runs.
                # Retain line breaks and two-space column separators for tables.
                display=re.sub(r'[ \t]{3,}','  ',quote) if self.compact else quote
                if self.compact:display=re.sub(r'\n[ \t]*\n(?:[ \t]*\n)*','\n',display)
                excerpts.append({'evidence_id':evidence_id,'text':display})
            rows.append({'source_id':source.id,'chunk_id':chunk.id,'locator':row.get('locator',chunk.locator),
                         'kind':source.kind,'excerpts':excerpts})
        return rows

    def ids(self, kind):
        return [key for key,(entry_kind,_) in self.entries.items() if entry_kind==kind]

    def schema(self, expected):
        schema=DraftReview.model_json_schema()
        fields=schema['$defs']['DraftFinding']['properties']
        fields['check_id']['enum']=list(expected)
        for field,kind in [('record_evidence','record'),('procedure_references','procedure')]:
            fields[field]['description']='Select supplied '+kind+' evidence IDs. Do not write quotes, source IDs or citation objects.'
            if self.ids(kind):fields[field]['items']['enum']=self.ids(kind)
        return output_schema(schema)

    def parse(self, text, expected):
        # Compatibility mode may add a single Markdown wrapper. Strip only an
        # entire wrapper; never salvage a fragment from surrounding prose.
        text=text.strip()
        match=re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```',text,re.I)
        if match:text=match.group(1)
        try:data=json.loads(text)
        except (ValueError,TypeError):
            raise ContractError('invalid_json','Return one complete JSON object matching the supplied schema.','response') from None
        # Case-only differences have one canonical interpretation. Do not
        # fuzzy-match IDs, paraphrases, enum synonyms, or factual content.
        known={key.casefold():key for key in expected}
        if isinstance(data,dict) and isinstance(data.get('findings'),list):
            for finding in data['findings']:
                if not isinstance(finding,dict):continue
                value=finding.get('check_id')
                if isinstance(value,str):finding['check_id']=known.get(value.strip().casefold(),value)
                for field in ['assessment','priority']:
                    if isinstance(finding.get(field),str):finding[field]=finding[field].strip().lower()
                for field in ['record_evidence','procedure_references']:
                    if isinstance(finding.get(field),list):
                        finding[field]=[item.strip().upper() if isinstance(item,str) else item for item in finding[field]]
        draft=DraftReview.model_validate(data)
        actual=[finding.check_id for finding in draft.findings]
        if len(set(actual))!=len(actual) or set(actual)!=set(expected):
            raise ContractError('checklist_coverage','Return each expected check ID exactly once: '+', '.join(expected)+'.')
        findings=[]
        for index,finding in enumerate(draft.findings):
            item=finding.model_dump()
            for field,kind in [('record_evidence','record'),('procedure_references','procedure')]:
                resolved=[]
                for evidence_id in item[field]:
                    entry=self.entries.get(evidence_id)
                    path=f'findings.{index}.{field}'
                    if entry is None:
                        raise ContractError('unknown_evidence_id','Select an evidence ID supplied in this review. Never invent an ID.',path)
                    if entry[0]!=kind:
                        raise ContractError('wrong_evidence_type','Select a '+kind+' evidence ID for this field.',path)
                    resolved.append(entry[1])
                item[field]=resolved
            findings.append(Finding.model_validate(item))
        return Review(overall_summary=draft.overall_summary,limitations=draft.limitations,findings=findings)


def validation_issues(error, expected):
    """Give actionable repair details without copying model text or source data."""
    if isinstance(error,ContractError):return [error.issue]
    if isinstance(error,ValidationError):
        fields=set(Finding.model_fields)|set(Review.model_fields)|{'response'}
        issues=[]
        for item in error.errors(include_input=False,include_url=False)[:6]:
            path='.'.join(str(v) if isinstance(v,int) else v if v in fields else '[field]' for v in item['loc']) or 'response'
            code=item['type']
            bounds={k:v for k,v in item.get('ctx',{}).items() if k in {'min_length','max_length'} and isinstance(v,int)}
            issues.append({'code':code,'path':path,'instruction':'Correct this field to match the supplied schema.',**bounds})
        return issues
    message=str(error)
    mappings=[
        ('narrative: assessment requires event and incoming attachment evidence','missing_incoming_citations','For narrative, cite both the saved event and the incoming attachment information. Use not_assessable if the comparison cannot be established.'),
        ('consistency: assessment requires event and MDR evidence','missing_cross_record_citations','Cite both primary event-record evidence and linked MDR evidence for a cross-record assessment. Use not_assessable when either side is unavailable.'),
        ('Duplicate check IDs','checklist_coverage','Return each expected check ID exactly once: '+', '.join(expected)+'.'),
        ('The review must cover','checklist_coverage','Return each expected check ID exactly once: '+', '.join(expected)+'.'),
        ('assessment requires record and rule evidence','missing_citations','A substantive assessment needs both record and procedure evidence IDs. Use not_assessable only when necessary evidence is unavailable.'),
        ('a priority needs a study action','missing_study_action','Supply a concrete study_action for a priority other than none.'),
        ('Extracted text digest mismatch','evidence_integrity','Reload the source documents; their extracted text failed integrity validation.'),
        ('Record ID mismatch','record_identity','Use sources for the same GCH record.'),
        ('Procedure revision is not approved','procedure_revision','Load an approved procedure revision.'),
        ('Original file digest is required','source_digest','Reload the original source document.'),
        ('Unknown source or wrong source type','invalid_citation_source','Select evidence IDs of the correct type from this review.'),
        ('Unverified excerpt','quote_mismatch','Select only the evidence IDs supplied in this review.'),
    ]
    for prefix,code,instruction in mappings:
        if prefix in message:return [{'code':code,'path':'findings','instruction':instruction}]
    return [{'code':'evidence_validation','path':'response','instruction':'The review failed source validation. Ask the trainer to inspect the loaded sources.'}]
