import re
from review_contract import ContractError
def validate_availability(review, sources, sections, sent):
    by_id={s.id:s for s in sources}
    complete=[s for s in sections if all((s.source_id,c.id) in sent for c in s.chunks)]
    for i,finding in enumerate(review.findings):
        text=' '.join([finding.what_was_done, finding.feedback, finding.study_action])
        if finding.check_id.startswith('mdr_'):
            forms=[s for s in sections if s.kind=='mdr' and by_id[s.source_id].document_id=='MDR']
            claims=re.finditer(
                r'\b(?:MDR(?:\s+narrative)?(?:\s+field(?:\s+values|s)?)?|embedded MDR(?:\s+field values)?|field values)'
                r'(?:\s+(?:B[1-7]|G7|H(?:1[12]?|2))(?:[–-](?:B[1-7]|H11))?(?:,|\s+and)?)*\s+'
                r'(?:(?:was|were|is|are)\s+)?not\s+(?:supplied|provided|available)(?:\s+for review)?', text,re.I)
            for claim in claims:
                version=re.search(r'\b(initial|follow[- ]?up)\s+$',text[:claim.start()],re.I)
                relevant=forms
                if version:
                    role=version[1].lower().replace(' ','-').replace('followup','follow-up')
                    relevant=[s for s in forms if role in by_id[s.source_id].name.lower()]
                if not relevant or not all(s in complete for s in relevant):
                    continue
                raise ContractError('supplied_mdr_claimed_missing',
                    'Linked MDR form text, including continuation pages, was supplied completely. Re-read the form and cite its readable values. '
                    'Name any specific blank, unreadable or ambiguous field and the affected version; do not claim the MDR values were not supplied. '
                    'Missing completion guidance is distinct from missing record evidence. Do not infer a favorable assessment or checkbox values.',
                    f'findings.{i}')
        for section in complete:
            source=by_id[section.source_id]
            appendix=re.match(r'^Appendix ([A-Z])\b',section.title,re.I)
            numbered=re.match(r'^(\d+)\.',section.title)
            if source.kind=='procedure':
                if appendix:label=r'Appendix\s+'+appendix[1]+r'\b'
                elif numbered:label=r'Section\s+'+numbered[1]+r'\b'
                else:continue
                docs=set(re.findall(r'\b\d{3}-(?:WI|P)\d+\b',text,re.I))
                if docs and source.document_id not in docs:continue
                if not docs and source.document_id not in {by_id[c.source_id].document_id for c in finding.procedure_references}:continue
            else:
                label=re.escape(section.title)
            assertion=r'(?:(?:was|were|is|are|they were)\s+not\s+(?:available|supplied|provided)|unavailable|missing)'
            match=(re.search(label+r'[^.!?]{0,140}?'+assertion,text,re.I) or
                   re.search(r'\b(?:unavailable|missing)\s+(?:'+label+r')',text,re.I))
            if match and source.kind=='procedure':
                tail=re.sub(r'^'+label,'',match[0],flags=re.I)
                if re.search(r'\b(?:date|record|fact|attempt|response|rationale|consultation|evidence|exception)\b',tail,re.I):match=None
            if match:
                raise ContractError('supplied_section_claimed_missing',
                    f'{source.document_id} {section.title} was supplied completely as {section.id}. Re-read its evidence before judging this check. Identify any genuinely missing record fact or dependent source precisely; do not change an assessment just to pass validation.',
                    f'findings.{i}.feedback')
        if finding.check_id=='timing':
            tables=[s for s in complete if by_id[s.source_id].document_id=='054-WI198' and re.match(r'^Appendix C\b',s.title)]
            if tables and re.search(r'(?:timeline table|clock rules|reporting.timeline table)[^.!?]{0,90}(?:not supplied|not available|not provided|unavailable)',text,re.I):
                raise ContractError('supplied_timeline_claimed_missing',
                    'The selected 054-WI198 Appendix C table was supplied completely. Use its report-type conditions and clock rules with the recorded awareness/submission dates. A missing exception or record fact must be named specifically.',
                    f'findings.{i}.feedback')