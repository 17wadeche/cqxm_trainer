"""Regression checks for missed governing evidence and overbroad missing claims.

Synthetic event content and mocked model responses only; bundled procedure
text is used to verify retrieval coverage, not to declare complaint compliance.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from config import GROUPS, ROOT
from context_budget import estimate_tokens
from engine import ReviewEngine, SplitEvidencePacket
from evidence_quality import validate_availability
from models import Chunk, EvidenceManifest, EvidenceSource, Finding, Review, extracted_digest
from procedure_sections import ProcedureIndex
from record_sections import RecordIndex
from repository import Repository
from review_contract import ContractError, EvidenceCatalog
from test_app import MockProvider


CHECKS={c[0]:c for group in GROUPS for c in group['checks']}


def event(pages,shift=0):
    chunks=[Chunk(id=f'c{i}',locator=f'PDF page {i+shift}, part 1',text=text) for i,text in enumerate(pages,1)]
    return EvidenceSource(id='synthetic-event',kind='record',name='SYNTHETIC DER.pdf',document_id='DER',
        record_id='TRAIN-001',revision=None,approved_revision=False,file_sha256='a'*64,
        extracted_text_sha256=extracted_digest(chunks),chunks=chunks)


PAGES=[
    'Detailed Event Report\nProduct Event Transaction ID: TRAIN-001\nSYNTHETIC ONLY',
    'Event Summary\nEvent Description text info\nReported loss of capture; device inactivated. Synthetic case only.',
    'Product Line Item Summary\nDevice Status Reason  Implanted-Out of Service\nProduct Returned to MDT?  NO\nRationale for No Rtn  Remains in Patient',
    'Investigation Summary\nSummary of Investigation text info\nClinical data reviewed; suspected cause recorded. Synthetic case only.',
    'Regulatory Report Summary\nRegulatory Report 123456789\nDecision Type  US FDA - MDR\nReport Sub Format  Initial\nAware Date  2025-07-25\nDue Date  2025-08-24\nDate Submitted  2025-08-14',
    'Communication Summary\nNo entries in this synthetic export.',
]


class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies=[EvidenceSource.model_validate(json.loads(p.read_text())['source'])
                      for p in (ROOT/'procedures').glob('*.json') if p.stem!='manifest']

    def packet(self,check_ids,provider=MockProvider):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        repo=Repository(Path(temp.name));self.addCleanup(repo.db.close)
        record=event(PAGES);sources=[record,*self.policies]
        for source in sources:repo.put(source,[])
        manifest=EvidenceManifest(mode='review',review_id='test',record_id='TRAIN-001',record_stage='Closed',
            generated_at='2026-09-30',prompt_version='test',template_version='test',model_version='mock',
            policy_selection='Synthetic test with bundled revisions',expected_check_ids=check_ids,sources=sources,limitations=[])
        engine=ReviewEngine(repo);client=provider('fake','mock','bearer');MockProvider.payloads=[]
        budget={'remaining':80}
        result=engine._group(client,[CHECKS[c] for c in check_ids],manifest,lambda *args:None,threading.Event(),budget)
        task=json.loads(MockProvider.payloads[0]['messages'][0]['content'])
        return result,task,budget,sources,client

    def supplied_text(self,task,source_id=None):
        return '\n'.join(e['text'] for row in task['initial_evidence'] if source_id is None or row['source_id']==source_id for e in row['excerpts'])

    def test_narrative_gets_actual_field_and_complete_governing_sections(self):
        _,task,budget,_,_=self.packet(['narrative'])
        text=' '.join(self.supplied_text(task).split())
        for value in ['Event Description text info','chronological description','does not include Medtronic speculations','Appendix E']:
            self.assertIn(value,text)
        self.assertTrue(all(s['status']=='complete' for s in budget['coverage'][0]['governing_procedures']))
        self.assertLess(estimate_tokens(task),60000)

    def test_gfe_gets_retained_status_no_return_rationale_and_completion_alternatives(self):
        _,task,budget,_,_=self.packet(['gfe'])
        text=' '.join(self.supplied_text(task).split())
        for value in ['Implanted-Out of Service','Remains in Patient','Rationale for no product return has been provided','The requiredinformation is received','Missing Required Information']:
            self.assertIn(value,text)
        self.assertTrue(all(s['status']=='complete' for s in budget['coverage'][0]['governing_procedures']))

    def test_timing_gets_table_continuation_aware_definition_and_computed_dates(self):
        _,task,budget,_,_=self.packet(['timing'])
        text=' '.join(self.supplied_text(task).split())
        for value in ['Appendix C','Supplemental','Within 30 calendar','AwareDate may or may not be the same date as','Aware Date vs. Notify Date']:
            self.assertIn(value,text)
        comparison=task['calendar_comparisons'][0]
        self.assertEqual(comparison['calendar_days'],20)
        self.assertEqual(comparison['calendar_days_before_displayed_due'],10)
        self.assertIn('no regulatory deadline inferred',comparison['method'])
        self.assertTrue(all(s['status']=='complete' for s in budget['coverage'][0]['governing_procedures']))

    def test_consultation_gets_investigation_not_only_decision(self):
        _,task,_,_,_=self.packet(['consultation'])
        self.assertIn('Clinical data reviewed',self.supplied_text(task,'synthetic-event'))
        candidates=RecordIndex([event(PAGES)]).candidates([CHECKS['consultation']])
        self.assertTrue(any(s.kind=='investigation' for s in candidates))

    def test_headings_and_record_anchors_survive_moved_pages_and_renumbering(self):
        record=event(PAGES,80);rows=RecordIndex([record]).anchor_pages([CHECKS['narrative'],CHECKS['gfe']])
        self.assertEqual({r['locator'] for r in rows},{'PDF page 82, part 1','PDF page 83, part 1'})
        policy=deepcopy(next(s for s in self.policies if s.document_id=='027-WI185'))
        for c in policy.chunks:
            c.text=c.text.replace('3. Complete Event Details','8. Complete Event Details').replace('Appendix E –Event Details','Appendix J –Event Details')
        index=ProcedureIndex([policy]);selected=index.candidates([CHECKS['narrative']],[policy])
        self.assertTrue(any(s.title.startswith('8.') for s in selected))
        self.assertTrue(any(s.title.startswith('Appendix J') for s in selected))

    def test_procedure_index_does_not_turn_prose_reference_into_section(self):
        index=ProcedureIndex(self.policies)
        titles=[s.title for s in index.sections if s.source_id==next(p.id for p in self.policies if p.document_id=='027-WI188')]
        self.assertEqual(sum(t.startswith('Appendix A') for t in titles),1)
        self.assertFalse(any('Formally Designated' in t for t in titles))

    def test_complete_section_cannot_be_claimed_unavailable(self):
        result,_,budget,sources,_=self.packet(['narrative'])
        result.findings[0].feedback='Confirm 027-WI185 Section 3 and Appendix E requirements; they were not available in this review.'
        sent={(r['source_id'],r['chunk_id']) for r in budget['coverage'][0]['supplied_chunks']}
        with self.assertRaisesRegex(ContractError,'was supplied completely'):
            validate_availability(result,sources,ProcedureIndex(sources).sections,sent)

    def test_supplied_timeline_cannot_be_claimed_missing(self):
        result,_,budget,sources,_=self.packet(['timing'])
        result.findings[0].feedback='The applicable U.S. reporting-timeline table and clock rules were not supplied. Obtain Appendix C.'
        sent={(r['source_id'],r['chunk_id']) for r in budget['coverage'][0]['supplied_chunks']}
        with self.assertRaisesRegex(ContractError,'table was supplied completely'):
            validate_availability(result,sources,ProcedureIndex(sources).sections,sent)

    def test_available_rule_does_not_invalidate_genuinely_missing_record_fact(self):
        result,_,budget,sources,_=self.packet(['timing'])
        result.findings[0].assessment='not_assessable'
        result.findings[0].feedback='Appendix C describes the rule, but the supplemental awareness date was not provided.'
        sent={(r['source_id'],r['chunk_id']) for r in budget['coverage'][0]['supplied_chunks']}
        validate_availability(result,sources,ProcedureIndex(sources).sections,sent)
        self.assertEqual(result.findings[0].assessment,'not_assessable')
        # Unread text is not silently treated as reviewed by availability checks.
        result.findings[0].feedback='Appendix C was not supplied in this packet.'
        validate_availability(result,sources,ProcedureIndex(sources).sections,set())

    def test_date_calculation_does_not_mix_reports_pages_or_ambiguous_values(self):
        ambiguous=PAGES[4]+'\nRegulatory Report 987654321\nAware Date 2025-08-01\nDate Submitted 2025-08-05'
        for pages in [[ambiguous],[PAGES[4].replace('Date Submitted  2025-08-14',''),'Regulatory Report Summary\nDate Submitted  2025-08-14'],[PAGES[4].replace('2025-07-25','2025-99-25')]]:
            source=event(pages);sent={(source.id,c.id) for c in source.chunks}
            self.assertEqual(RecordIndex([source]).calendar_comparisons(sent),[])

    def test_compact_model_text_retains_original_verbatim_citation(self):
        source=event(['Event Summary\n  Device Status Reason             Implanted-Out of Service'])
        registry=EvidenceCatalog([source],compact=True)
        row=registry.add([{'source_id':source.id,'chunk_id':source.chunks[0].id,'text':source.chunks[0].text}])[0]
        excerpt=row['excerpts'][0]
        self.assertNotIn('             ',excerpt['text'])
        self.assertEqual(registry.entries[excerpt['evidence_id']][1].quote,source.chunks[0].text)

    def test_large_combined_checks_split_before_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=Repository(Path(directory))
            try:
                record=event(PAGES);sources=[record,*self.policies]
                for s in sources:repo.put(s,[])
                evidence=EvidenceManifest(mode='review',review_id='test',record_id='TRAIN-001',record_stage='Closed',generated_at='test',prompt_version='test',template_version='test',model_version='mock',policy_selection='test',expected_check_ids=['reportability','timing'],sources=sources,limitations=[])
                MockProvider.payloads=[];client=MockProvider('fake','mock','bearer')
                with self.assertRaises(SplitEvidencePacket):
                    ReviewEngine(repo)._group(client,[CHECKS['reportability'],CHECKS['timing']],evidence,lambda *a:None,threading.Event(),input_target=35000)
                self.assertEqual(MockProvider.payloads,[])
            finally:repo.db.close()

    def test_substantive_verification_is_required_without_forcing_positive_labels(self):
        class VerifyProvider(MockProvider):
            def message(self,system,messages,**kwargs):
                answer=super().message(system,messages,**kwargs)
                if kwargs.get('schema'):
                    verification=any(isinstance(m['content'],str) and '"phase": "evidence and applicability verification"' in m['content'] for m in messages)
                    data=json.loads(answer['content'][0]['text'])
                    data['findings'][0]['feedback']='Verified uncertainty retained.' if verification else 'Draft requires verification.'
                    answer['content'][0]['text']=json.dumps(data)
                return answer
        result,_,budget,_,_=self.packet(['narrative'],VerifyProvider)
        self.assertEqual(result.findings[0].feedback,'Verified uncertainty retained.')
        self.assertEqual(result.findings[0].assessment,'needs_trainer_review')
        self.assertTrue(budget['coverage'][0]['accuracy_verification'])


if __name__=='__main__':unittest.main()
