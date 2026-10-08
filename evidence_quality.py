"""Reject concrete claims that supplied sections were unavailable.

This is an availability check, not a clinical or procedural assessment. It never
selects a finding's assessment or fills missing record facts.
"""
import re

from review_contract import ContractError


def validate_availability(review, sources, sections, sent):
    by_id={s.id:s for s in sources}
    complete=[s for s in sections if all((s.source_id,c.id) in sent for c in s.chunks)]
    for i,finding in enumerate(review.findings):
        text=finding.feedback+' '+finding.study_action
        for section in complete:
            source=by_id[section.source_id]
            appendix=re.match(r'^Appendix ([A-Z])\b',section.title,re.I)
            numbered=re.match(r'^(\d+)\.',section.title)
            if source.kind=='procedure':
                if appendix:label=r'Appendix\s+'+appendix[1]+r'\b'
                elif numbered:label=r'Section\s+'+numbered[1]+r'\b'
                else:continue
                # A document mention must identify the source; avoid treating
                # another procedure's Appendix A as this one.
                docs=set(re.findall(r'\b\d{3}-(?:WI|P)\d+\b',text,re.I))
                if docs and source.document_id not in docs:continue
                if not docs and source.document_id not in {by_id[c.source_id].document_id for c in finding.procedure_references}:continue
            else:
                label=re.escape(section.title)
            assertion=r'(?:(?:was|were|is|are|they were)\s+not\s+(?:available|supplied|provided)|unavailable|missing)'
            match=(re.search(label+r'[^.!?]{0,140}?'+assertion,text,re.I) or
                   re.search(r'\b(?:unavailable|missing)\s+(?:'+label+r')',text,re.I))
            # An available rule can legitimately be cited while explaining a
            # missing record date/response. Do not conflate the two subjects.
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
