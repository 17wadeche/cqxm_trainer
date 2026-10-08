import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
from config import (GROUPS, ROOT, VERSION, ENVIRONMENT, RETRIEVAL_OUTPUT_TOKENS, REVIEW_OUTPUT_TOKENS,
                    MAX_OUTPUT_TOKENS, MAX_CHECKS_PER_BATCH, MAX_REVIEW_REQUESTS, TARGET_INPUT_TOKENS)
from ingest import source_from_bytes
from mdt import MDTClient, ProviderError, response_text
from models import EvidenceManifest, Review, Finding, validate_traceability
from review_contract import EvidenceCatalog, validation_issues
from record_sections import RecordIndex, embedded_mdrs
from procedure_sections import ProcedureIndex, coverage
from evidence_quality import validate_availability
from context_budget import estimate_tokens
from render_report import render
TOOLS = [
    {"name":"read_procedure_section","description":"Read a governing procedure section or appendix from the supplied outline, with its complete table, conditions and continuation pages. Start at offset 0 and follow next_offset until null.",
     "input_schema":{"type":"object","properties":{"source_id":{"type":"string"},"section_id":{"type":"string"},"offset":{"type":"integer","minimum":0}},"required":["source_id","section_id","offset"],"additionalProperties":False}},
    {"name":"read_record_section","description":"Read a heading-defined record section from the supplied outline, including continuation pages. Start at offset 0, then follow next_offset until null. Sections are discovered from headings, never fixed page numbers.",
     "input_schema":{"type":"object","properties":{"source_id":{"type":"string"},"section_id":{"type":"string"},"offset":{"type":"integer","minimum":0}},"required":["source_id","section_id","offset"],"additionalProperties":False}},
    {"name":"read_chunks","description":"Read consecutive original chunks in a record or procedure, for complete tables, applicability, definitions or exceptions. Follow next_chunk_id to continue. Do not stop at a clause when surrounding requirements are needed.",
     "input_schema":{"type":"object","properties":{"source_id":{"type":"string"},"chunk_id":{"type":"string"}},"required":["source_id","chunk_id"],"additionalProperties":False}},
    {"name": "search_records", "description": "Search the event record, incoming attachments (rep/patient/other correspondence), and linked MDR versions. Returns source IDs, chunk IDs, original locations, and exact text. Query for evidence needed for the current checks.",     
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "search_procedures", "description": "Search only the uploaded, selected controlled procedure revisions. Returns exact text and source locations. Use this to find actual requirements and their applicability conditions; do not use model memory for policy.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "read_section", "description": "Read a known source chunk and its immediate neighbors to recover surrounding requirements, exceptions, or table cells. Only source and chunk IDs from this review are allowed.",
     "input_schema": {"type": "object", "properties": {"source_id": {"type": "string"}, "chunk_id": {"type": "string"}}, "required": ["source_id", "chunk_id"], "additionalProperties": False}},
    {"name": "calendar_days_between", "description": "Compute end minus start in calendar days for two ISO dates. This does not choose a regulatory clock start, deadline, inclusive-counting rule, jurisdiction, or exception; those require the applicable cited procedure.",
     "input_schema": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}, "required": ["start", "end"], "additionalProperties": False}},
]
def unavailable(check, message):
    return Finding(check_id=check[0], record_element=check[1], what_was_done=message,
        record_evidence=[], procedure_references=[], assessment="not_assessable",
        feedback="Supply the missing inputs and ask the trainer to confirm this check's scope and applicability.",
        priority="medium", study_action=message)

class SplitEvidencePacket(Exception):
    """Split checks before any API call when their governing evidence won't fit."""
class ReviewEngine:
    def __init__(self, repository, provider_factory=MDTClient):
        self.repo = repository
        self.provider_factory = provider_factory
        self.system = (ROOT / "review_prompt.md").read_text(encoding="utf-8") + "\nUse the retrieval tools to verify the supplied sources. Never claim to have reviewed the original visuals. Return one finding per expected check ID. Citation fields are arrays of supplied evidence IDs such as E0001; do not write quotes or source/chunk citation objects. The application inserts the exact stored excerpts. Do not include conversation or internal reasoning."
        self.retrieval_system = self.system + "\nCURRENT PHASE: gather evidence before writing the report. Defer all findings and report JSON until the final phase. Use the read-only retrieval tools to fill evidence gaps. When ready, return only READY. Do not draft findings or narrate your work in this phase."
    def _message(self, client, system, messages, progress, cancelled, budget, phase, *, tools=None, schema=None, max_tokens):
        limit = min(max_tokens, MAX_OUTPUT_TOKENS)
        length_retries = recovery_retries = 0
        retry_system = system
        while True:
            if cancelled.is_set():
                raise InterruptedError("Review cancelled")
            if budget['remaining'] <= 0:
                raise ProviderError('The review reached its request limit. No report was accepted. Ask your trainer to inspect the source scope.')
            budget['remaining'] -= 1
            try:
                answer = client.message(retry_system, messages, tools=tools, schema=schema, max_tokens=limit)
                if sum(c.get('type') == 'tool_use' for c in answer['content']) > 8:
                    raise ProviderError('The model requested too many tool calls in one turn.',stop_reason='too_many_tool_calls')
                return answer
            except ProviderError as exc:
                if exc.status == 503 or exc.stop_reason == 'too_many_tool_calls':
                    if recovery_retries >= 3 or budget['remaining'] <= 0:
                        raise
                    recovery_retries += 1
                    if exc.stop_reason == 'too_many_tool_calls':
                        retry_system = system + '\nRequest at most 8 read-only tool calls in this turn. Defer additional calls to later turns.'
                    progress(f'Waiting 30 seconds before retrying {phase} ({recovery_retries}/3). Your progress is saved…')
                    if cancelled.wait(30):
                        raise InterruptedError('Review cancelled')
                    progress(f'Retrying {phase}…')
                    continue
                if exc.stop_reason != 'max_tokens':
                    raise
                if limit >= MAX_OUTPUT_TOKENS or length_retries == 2:
                    raise ProviderError(f'The model still reached the response-length limit while {phase} (stop_reason=max_tokens; limit={limit}). Automatic length retries are exhausted. No report was accepted.',
                                        stop_reason='max_tokens', output_limit=limit) from None
                limit = min(limit*2, MAX_OUTPUT_TOKENS)
                length_retries += 1
                progress(f'The answer was cut short. Retrying {phase} with more room…')
    def _tools(self, name, args, sources):
        allowed = {s.id: s for s in sources}
        if not isinstance(args, dict):
            raise ValueError("Tool arguments must be an object")
        if name in {'read_record_section','read_procedure_section'}:
            if set(args)!={'source_id','section_id','offset'}:raise ValueError('Provide source_id, section_id and offset')
            index=RecordIndex(sources) if name=='read_record_section' else ProcedureIndex(sources)
            rows,page=index.read(args['source_id'],args['section_id'],args['offset'])
            return {'chunks':rows,**page}
        if name=='read_chunks':
            if set(args)!={'source_id','chunk_id'}:raise ValueError('Provide source_id and chunk_id')
            source=allowed.get(args['source_id'])
            pos=next((i for i,c in enumerate(source.chunks) if c.id==args['chunk_id']),None) if source else None
            if pos is None:raise ValueError('Unknown source or chunk')
            chunks=source.chunks[pos:pos+8]
            return {'chunks':[{'source_id':source.id,'chunk_id':c.id,'locator':c.locator,'text':c.text} for c in chunks],
                    'next_chunk_id':source.chunks[pos+len(chunks)].id if pos+len(chunks)<len(source.chunks) else None}
        if name in {"search_records", "search_procedures"}:
            if set(args) != {"query"} or not isinstance(args['query'], str):
                raise ValueError("Provide a single query string")
            kind = "record" if name == "search_records" else "procedure"
            return self.repo.search(args['query'][:500], [s.id for s in sources if s.kind == kind], 4)
        if name == "read_section":
            if set(args) != {"source_id", "chunk_id"}:
                raise ValueError("Provide source_id and chunk_id")
            source = allowed.get(args['source_id'])
            if source is None:
                raise ValueError("Source is outside this review")
            pos = next((i for i, c in enumerate(source.chunks) if c.id == args['chunk_id']), None)
            if pos is None:
                raise ValueError("Unknown chunk")
            return [{"source_id": source.id, "chunk_id": c.id, "locator": c.locator, "text": c.text}
                    for c in source.chunks[max(0, pos-1):pos+2]]
        if name == "calendar_days_between":
            if set(args) != {"start", "end"}:
                raise ValueError("Provide start and end ISO dates")
            return {"calendar_days": (date.fromisoformat(args['end']) - date.fromisoformat(args['start'])).days,
                    "method": "end minus start; no regulatory deadline inferred"}
        raise ValueError("Unknown tool; only document retrieval and date arithmetic are allowed")
    def _group(self, client, checks, evidence, progress, cancelled, budget=None, prior_findings=None, input_target=TARGET_INPUT_TOKENS):
        if budget is None:
            budget = {'remaining': MAX_REVIEW_REQUESTS}
        proc_ids = list(dict.fromkeys(d for c in checks for d in c[2]))
        record_ids = [s.id for s in evidence.sources if s.kind == 'record']
        procedure_ids = [s.id for s in evidence.sources if s.document_id in proc_ids and s.kind == 'procedure']
        query = " ".join(c[1] for c in checks)
        registry=EvidenceCatalog(evidence.sources,compact=True)
        index=RecordIndex(evidence.sources)
        policies=ProcedureIndex(evidence.sources)
        governing=policies.candidates(checks,evidence.sources)
        sent=set()
        seeds=[]
        catalog = [{"source_id": s.id, "document_id": s.document_id, "revision": s.revision,
                    "kind": s.kind, "sections": len(s.chunks),
                    "outline":index.outline(s.id) if s.kind=='record' else policies.outline(s.id),"name":s.name,
                    "start": registry.add([{'source_id':s.id,'chunk_id':s.chunks[0].id,
                                            'text':s.chunks[0].text[:600]}])[0]}
                   for s in evidence.sources]
        task = {"record_id": evidence.record_id, "stage": evidence.record_stage,
                "policy_selection": evidence.policy_selection,
                "expected_checks": [{"id": c[0], "focus": c[1], "required_documents": c[2]} for c in checks],
                "input_limitations": evidence.limitations, "sources": catalog, "initial_evidence": seeds,
                "section_coverage":[], "governing_procedure_coverage":[],
                "earlier_findings_for_cross_check":[{'check_id':f.check_id,'assessment':f.assessment,'observation':f.what_was_done,'feedback':f.feedback}
                    for f in (prior_findings or [])] if any(c[0] in {'consistency','closure'} for c in checks) else []}
        def fits(value,reserve=0):
            return estimate_tokens({'system':self.system,'tools':TOOLS,'messages':value})*getattr(client,'estimate_scale',1)+reserve < input_target
        def seed_rows(rows,reserve):
            nonlocal registry
            for row in rows:
                key=(row['source_id'],row['chunk_id'])
                if key in sent:continue
                value,staged=registry.preview([row])
                if not fits({**task,'initial_evidence':seeds+value},reserve=reserve):continue
                registry=staged;seeds.extend(value);sent.add(key)
        needed=[{'source_id':section.source_id,'chunk_id':c.id,'locator':c.locator,'text':c.text}
                for section in governing for c in section.chunks]
        needed+=policies.definition_pages(checks,evidence.sources)+index.anchor_pages(checks)
        needed=list({(r['source_id'],r['chunk_id']):r for r in needed}.values())
        value,staged=registry.preview(needed)
        if fits({**task,'initial_evidence':value},reserve=12000):
            registry=staged;seeds.extend(value)
            sent.update((r['source_id'],r['chunk_id']) for r in needed)
        elif len(checks)>1:
            raise SplitEvidencePacket()
        else:
            seed_rows(needed,12000)
        task['governing_procedure_coverage']=coverage(governing,sent)
        derived={(s.file_sha256,c.id) for s in evidence.sources if s.document_id=='MDR' for c in s.chunks}
        source_map={s.id:s for s in evidence.sources}
        for section in index.candidates(checks):
            added=0
            for chunk in section.chunks:
                source=source_map[section.source_id]
                if source.document_id=='DER' and section.kind=='mdr' and (source.file_sha256,chunk.id) in derived:continue
                key=(section.source_id,chunk.id)
                if key in sent:continue
                value,staged=registry.preview([{'source_id':section.source_id,'chunk_id':chunk.id,'locator':chunk.locator,'text':chunk.text}])
                if not fits({**task,'initial_evidence':seeds+value},reserve=10000):continue
                registry=staged;seeds.extend(value);sent.add(key);added+=1
            supplied=sum((section.source_id,chunk.id) in sent for chunk in section.chunks)
            task['section_coverage'].append({**section.outline(),'source_id':section.source_id,'supplied_chunks':supplied,
                'status':'complete' if supplied==len(section.chunks) else 'partial or not yet supplied'})
        if len(checks)>2 and any(s['status']!='complete' for s in task['section_coverage']):
            raise SplitEvidencePacket()
        hits=self.repo.search(query,record_ids,4)+self.repo.search(query,procedure_ids,6)
        expanded=[]
        for hit in hits:expanded.extend(self._tools('read_section',{'source_id':hit['source_id'],'chunk_id':hit['chunk_id']},evidence.sources))
        for row in expanded:
            key=(row['source_id'],row['chunk_id'])
            if key in sent:continue
            value,staged=registry.preview([row])
            if fits({**task,'initial_evidence':seeds+value},reserve=8000):
                registry=staged;seeds.extend(value);sent.add(key)
        task['initial_evidence']=seeds
        task['calendar_comparisons']=index.calendar_comparisons(sent) if any(c[0]=='timing' for c in checks) else []
        messages = [{"role": "user", "content": json.dumps(task, ensure_ascii=False)}]
        for round_number in range(6):
            if cancelled.is_set():
                raise InterruptedError("Review cancelled")
            answer = self._message(client, self.retrieval_system, messages, progress, cancelled, budget,
                'gathering evidence', tools=TOOLS, max_tokens=RETRIEVAL_OUTPUT_TOKENS)
            calls = [c for c in answer['content'] if c.get('type') == 'tool_use']
            if not calls:
                break
            if len(calls) > 8:
                raise ProviderError("The model requested too many tool calls in one turn.")
            messages.append({"role": "assistant", "content": answer['content']})
            results = []
            for call in calls:
                progress(f"Reading evidence for {checks[0][1].lower()}")
                try:
                    value = self._tools(call.get('name'), call.get('input'), evidence.sources)
                    staged=registry
                    newly_sent=set()
                    if call.get('name') in {'search_records','search_procedures','read_section','read_record_section','read_procedure_section','read_chunks'}:
                        meta={k:v for k,v in value.items() if k!='chunks'} if isinstance(value,dict) else {}
                        rows=value['chunks'] if isinstance(value,dict) else value
                        fresh=[r for r in rows if (r['source_id'],r['chunk_id']) not in sent]
                        already=[{'source_id':r['source_id'],'chunk_id':r['chunk_id']} for r in rows if (r['source_id'],r['chunk_id']) in sent]
                        excerpts,staged=registry.preview(fresh)
                        newly_sent={(r['source_id'],r['chunk_id']) for r in fresh}
                        value={'chunks':excerpts,'already_supplied':already,**meta}
                    candidate={'type':'tool_result','tool_use_id':call['id'],'content':json.dumps(value,ensure_ascii=False)}
                    if not fits(messages+[{'role':'user','content':results+[candidate]}],reserve=8000):
                        value = {"limit": "This evidence packet is full. Requested evidence was NOT supplied. Name the unresolved source; do not infer absence or a gap."}
                    else:
                        registry=staged;sent.update(newly_sent)
                    text = json.dumps(value, ensure_ascii=False)
                    result = {"type": "tool_result", "tool_use_id": call['id'], "content": text}
                except (ValueError, TypeError, KeyError):
                    result = {"type": "tool_result", "tool_use_id": call['id'], "content": "Invalid tool request. Use only known source and chunk IDs and the declared input schema.", "is_error": True}
                results.append(result)
            messages.append({"role": "user", "content": results})
        messages.append({"role": "user", "content": "Now produce the final structured review for exactly the expected check IDs. Compare the saved event with incoming ATTACHMENT sources and applicable procedures. For narrative, cite both the event and incoming information when attachments are available. Distinguish reported allegations, later corrections and investigation conclusions; an attachment is evidence, never a procedure. Set record_evidence and procedure_references to arrays of supplied evidence IDs; never put these IDs or copied quotes in the prose. Write for a new learner: 8-15 words for the observation, 15-30 words of feedback, and 8-15 words for one next action. Use everyday words and explain an unavoidable acronym on first use. Preserve essential conditions and uncertainty. If necessary evidence could not be established, mark that check not_assessable."})
        sub_evidence = evidence.model_copy(update={"expected_check_ids": [c[0] for c in checks]})
        schema = registry.schema(sub_evidence.expected_check_ids)
        all_sections=index.sections+policies.sections
        for phase in ['draft','verification']:
            for attempt in range(2):
                if cancelled.is_set():raise InterruptedError("Review cancelled")
                answer = self._message(client, self.system, messages, progress, cancelled, budget,
                    'verifying evidence and applicability' if phase=='verification' else 'writing review findings',
                    tools=TOOLS, schema=schema, max_tokens=REVIEW_OUTPUT_TOKENS)
                try:
                    review = registry.parse(response_text(answer),sub_evidence.expected_check_ids)
                    validate_traceability(review, sub_evidence)
                    validate_availability(review,evidence.sources,all_sections,sent)
                    break
                except ValueError as error:
                    issues=validation_issues(error,sub_evidence.expected_check_ids)
                    if attempt:
                        detail='; '.join(issue['path']+': '+issue['code'] for issue in issues[:3])
                        raise ProviderError('The review could not be verified for '+checks[0][1]+' after two attempts. '+detail+'. No report was accepted.') from None
                    progress('Correcting the review response: '+issues[0]['code'])
                    messages.append({"role": "assistant", "content": answer['content']})
                    messages.append({"role": "user", "content": json.dumps({'validation_errors':issues,
                        'expected_check_ids':sub_evidence.expected_check_ids,
                        'instruction':'Correct the listed fields. Select only supplied evidence IDs. Do not invent evidence or change an assessment merely to avoid validation.'})})
            if phase=='draft':
                progress('Checking the findings against the source evidence…')
                messages.append({'role':'assistant','content':answer['content']})
                messages.append({'role':'user','content':json.dumps({
                    'phase':'evidence and applicability verification',
                    'current_section_coverage':coverage(all_sections,sent),
                    'calendar_comparisons':index.calendar_comparisons(sent) if any(c[0]=='timing' for c in checks) else [],
                    'instruction':
                        'Re-check every draft finding against the original supplied evidence and return the corrected final review using the same schema. '
                        'This is a substantive accuracy check, not a request for more favorable assessments. '
                        'For every not_assessable finding, distinguish a genuinely absent source/fact from an available section you did not use. '
                        'Use complete governing sections and applicable exceptions; do not claim supplied rules or appendices are unavailable. '
                        'Assess the supported part of a check and qualify the specific unresolved part; one missing dependent document must not erase all supported observations. '
                        'Narrative: evaluate Event Description text info (including Text Info/As Reported variants), not the brief description or investigation conclusion. '
                        'GFE: distinguish required missing information, product return and requested customer response. Identify the actual missing required information before prescribing attempts. '
                        'Compare retained/implanted/inactivated status and the no-return rationale with the instruction\'s alternative completion criteria. Never suggest explantation solely to obtain a return. '
                        'Timing: use the actual jurisdiction, initial/supplemental report, aware date, submission/acknowledgement and cited clock rules. '
                        'A timeliness evaluation is not automatically required for an on-time report; verify its trigger in the instruction. '
                        'Consultation: read the supplied Investigation Summary and distinguish a conditional consultation requirement from an automatic one. '
                        'Consistency: describe the factual comparison under applicable event-detail/coding requirements; do not invent a separate mandatory comparison procedure. '
                        'Do not add generic visual/extraction caveats to rows when no relevant ambiguity exists. Keep the same concise Word-report length.'})})
        budget.setdefault('coverage',[]).append({'checks':sub_evidence.expected_check_ids,
            'supplied_chunks':[{'source_id':s,'chunk_id':c} for s,c in sorted(sent)],
            'sections':coverage(all_sections,sent), 'governing_procedures':coverage(governing,sent),
            'accuracy_verification':True})
        return review
    def run(self, job_id, record_id, stage, policy_selection, files, connection, progress, cancelled, *, attachment_limits=None):
        sources, warnings = [], list(attachment_limits or [])
        attachment_coverage = []
        for kind, name, data in files:
            try:
                source, limits = source_from_bytes(name, data, str(uuid4()), 'record', kind, record_id)
            except (ValueError, OSError) as error:
                if kind != 'ATTACHMENT': raise
                warnings.append(f'Incoming attachment {name} could not be read: {error}')
                attachment_coverage.append({'name':name,'status':'unreadable','reason':str(error)})
                continue
            self.repo.put(source, limits)
            sources.append(source)
            warnings.extend(limits)
            if kind == 'ATTACHMENT':
                attachment_coverage.append({'name':name,'status':'read','source_id':source.id,'file_sha256':source.file_sha256,'warnings':limits})
                continue
            derived,limits=embedded_mdrs(source)
            for form in derived:
                self.repo.put(form,[]);sources.append(form)
            warnings.extend(limits)
        if not any(s.document_id in {'PESR','DER'} for s in sources):
            raise ValueError("A Detailed Event Report or PESR is required.")
        if not any(s.document_id=='ATTACHMENT' for s in sources):
            warnings.append('No readable incoming attachments were supplied. Accuracy against the original rep, patient or other report could not be checked.')
        selected = self.repo.active_procedures()
        for source, limits in selected:
            sources.append(source)
            warnings.extend(limits)
        expected = [c[0] for group in GROUPS for c in group['checks']]
        warnings.append("Training feedback only. Source excerpts are verified for text presence; trainer judgment is required for correctness and applicability.")
        evidence = EvidenceManifest(mode='review', review_id=job_id, record_id=record_id,
            record_stage=stage, generated_at=datetime.now(timezone.utc).isoformat(),
            prompt_version=VERSION, model_version=connection['model'], template_version=VERSION,
            policy_selection=policy_selection, expected_check_ids=expected, sources=sources,
            limitations=list(dict.fromkeys(warnings)))
        by_doc = {s.document_id for s in sources if s.kind == 'procedure'}
        has_mdr = any(s.document_id == 'MDR' for s in sources)
        findings, extra_limits, client = [], [], None
        budget = {'remaining': MAX_REVIEW_REQUESTS}
        for idx, group in enumerate(GROUPS):
            progress(f"Reviewing {group['name'].lower()}", 15 + idx*14)
            eligible = []
            for check in group['checks']:
                missing = [d for d in check[2] if d not in by_doc]
                if check[3] and not has_mdr:
                    missing.append('matching MDR report')
                if missing:
                    message = "Missing input: " + ", ".join(missing) + "."
                    findings.append(unavailable(check, message))
                    extra_limits.append(check[1] + " — " + message)
                else:
                    eligible.append(check)
            if not eligible:
                continue
            if client is None:
                client = self.provider_factory(connection['token'], connection['model'], connection['auth_style'],
                    environment=ENVIRONMENT)
                client.structured_mode = connection.get('structured_mode', 'auto')
            packets=[eligible[start:start+MAX_CHECKS_PER_BATCH] for start in range(0,len(eligible),MAX_CHECKS_PER_BATCH)]
            while packets:
                batch=packets.pop(0)
                progress(f"Reviewing {batch[0][1].lower()}")
                for retry in range(3):
                    try:
                        result = self._group(client, batch, evidence, progress, cancelled, budget,
                                             prior_findings=findings,input_target=TARGET_INPUT_TOKENS//(2**retry))
                        break
                    except SplitEvidencePacket:
                        midpoint=(len(batch)+1)//2
                        packets[0:0]=[batch[:midpoint],batch[midpoint:]]
                        progress('Reviewing these areas separately to include their governing evidence…')
                        result=None
                        break
                    except ProviderError as error:
                        if error.stop_reason not in {'local_context_budget','input_context_budget','model_context_window_exceeded'} or retry==2:raise
                        progress('Preparing a smaller evidence packet for this check…')
                if result is None:continue
                findings.extend(result.findings)
                extra_limits.extend(result.limitations)
        if cancelled.is_set():
            raise InterruptedError("Review cancelled")
        order = {v: i for i, v in enumerate(expected)}
        findings.sort(key=lambda f: order[f.check_id])
        assessed = sum(f.assessment != 'not_assessable' for f in findings)
        if client is None:
            evidence.model_version = "No model call — required procedure inputs missing"
        elif getattr(client, 'structured_mode', '') == 'validated_json':
            extra_limits.append('The gateway does not support native structured output for this request. JSON shape, checklist coverage and source excerpts were validated locally before accepting the report.')
        if client is not None:
            reported = sorted(getattr(client,'reported_models',set()))
            if reported and reported != [connection['model']]:
                evidence.model_version = 'Requested: '+connection['model']+'; gateway reported: '+', '.join(reported)
        if client is not None and getattr(client, 'tool_mode', '') == 'validated_json':
            extra_limits.append('Retrieval used a locally validated JSON plan because the gateway rejected native tool parameters. Only the same approved read-only tools were available.')
        review = Review(overall_summary=f"{assessed} of {len(findings)} review areas have an assessment based on the available inputs. The remaining areas need additional evidence or applicable procedures. Discuss the findings and study priorities with the trainer; this is not an overall compliance determination.",
                        limitations=list(dict.fromkeys(extra_limits)), findings=findings)
        validate_traceability(review, evidence)
        progress("Creating the Word report", 92)
        out = self.repo.directory / 'reports' / job_id
        out.mkdir(parents=True, exist_ok=True)
        render(review, evidence, out / 'review.docx')
        (out / 'review.json').write_text(review.model_dump_json(indent=2), encoding='utf-8')
        (out / 'evidence.json').write_text(evidence.model_dump_json(indent=2), encoding='utf-8')
        (out / 'retrieval_coverage.json').write_text(json.dumps(budget.get('coverage',[]),indent=2),encoding='utf-8')
        (out / 'context_usage.json').write_text(json.dumps(getattr(client,'context_usage',[]),indent=2),encoding='utf-8')
        (out / 'attachment_coverage.json').write_text(json.dumps({'files':attachment_coverage,'collection_limits':attachment_limits or []},indent=2),encoding='utf-8')
        return {"review": review.model_dump(), "sources": [{"id": s.id, "name": s.name, "document_id": s.document_id, "revision": s.revision} for s in sources],
                "record_id": record_id, "model": evidence.model_version, "limitations": evidence.limitations,
                "usage": client.usage if client else {}, "demo": False}
def demo_report(directory, job_id):
    review = Review.model_validate_json((ROOT/'examples/demo_review.json').read_text(encoding='utf-8'))
    evidence = EvidenceManifest.model_validate_json((ROOT/'examples/demo_evidence.json').read_text(encoding='utf-8'))
    evidence.review_id = job_id
    evidence.generated_at = datetime.now(timezone.utc).isoformat()
    evidence.template_version = VERSION
    out = directory / 'reports' / job_id
    out.mkdir(parents=True, exist_ok=True)
    render(review, evidence, out/'review.docx')
    (out/'review.json').write_text(review.model_dump_json(indent=2), encoding='utf-8')
    (out/'evidence.json').write_text(evidence.model_dump_json(indent=2), encoding='utf-8')
    return {"review": review.model_dump(), "sources": [{"id": s.id, "name": s.name, "document_id": s.document_id, "revision": s.revision} for s in evidence.sources],
            "record_id": evidence.record_id, "model": evidence.model_version, "limitations": evidence.limitations,
            "usage": {}, "demo": True}