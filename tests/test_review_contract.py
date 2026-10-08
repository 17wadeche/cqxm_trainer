"""Synthetic evidence IDs are resolved locally, never trusted as model quotes."""
from copy import deepcopy
import json
import unittest

from pydantic import ValidationError

from ingest import source_from_bytes
from models import EvidenceManifest, validate_traceability
from review_contract import ContractError, EvidenceCatalog, validation_issues


class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.record,_=source_from_bytes('PESR.txt',b'Product Event Summary Report\nTRAIN-001\nSynthetic record only.',
            'record-1','record','PESR','TRAIN-001')
        self.rule,_=source_from_bytes('rule.txt',b'Synthetic rule only. Check the supplied training identifier.',
            'rule-1','procedure','027-P043',revision='TEST',approved=True)
        self.catalog=EvidenceCatalog([self.record,self.rule])
        self.rows=self.catalog.add([{'source_id':s.id,'chunk_id':s.chunks[0].id,'text':s.chunks[0].text}
            for s in [self.record,self.rule]])
        self.record_id=self.rows[0]['excerpts'][0]['evidence_id']
        self.rule_id=self.rows[1]['excerpts'][0]['evidence_id']
        self.data={'overall_summary':'Synthetic example.', 'limitations':[], 'findings':[{
            'check_id':'CHECK_1','record_element':'Identifier','what_was_done':'Training identifier supplied.',
            'record_evidence':[self.record_id],'procedure_references':[self.rule_id],
            'assessment':'needs_trainer_review','feedback':'Discuss the synthetic example with the trainer.',
            'priority':'low','study_action':'Read the synthetic rule.'}]}
        self.evidence=EvidenceManifest(mode='review',review_id='test',record_id='TRAIN-001',record_stage='Intake',
            generated_at='2026-09-28',prompt_version='test',model_version='mock',template_version='test',
            policy_selection='Synthetic',expected_check_ids=['CHECK_1'],sources=[self.record,self.rule],limitations=[])

    def parse(self,data=None):
        return self.catalog.parse(json.dumps(self.data if data is None else data),['CHECK_1'])

    def test_exact_quotes_and_locations_come_from_loaded_sources(self):
        review=self.parse()
        cite=review.findings[0].record_evidence[0]
        self.assertEqual(cite.quote,self.record.chunks[0].text)
        self.assertEqual(cite.source_id,self.record.id)
        self.assertEqual(cite.chunk_id,self.record.chunks[0].id)
        validate_traceability(review,self.evidence)

    def test_long_excerpts_split_into_bounded_verbatim_spans(self):
        text='Product Event Summary Report\nTRAIN-001\n'+('Synthetic sentence with punctuation and spacing. '*40).strip()
        source,_=source_from_bytes('long.txt',text.encode(),'long','record','PESR','TRAIN-001')
        registry=EvidenceCatalog([source])
        rows=registry.add([{'source_id':source.id,'chunk_id':c.id,'text':c.text} for c in source.chunks])
        self.assertGreater(len(registry.entries),1)
        for row in rows:
            chunk=next(c for c in source.chunks if c.id==row['chunk_id'])
            for excerpt in row['excerpts']:
                self.assertLessEqual(len(excerpt['text']),600)
                self.assertIn(excerpt['text'],chunk.text)

    def test_unknown_and_wrong_kind_ids_are_rejected(self):
        for bad,code in [('E9999','unknown_evidence_id'),(self.rule_id,'wrong_evidence_type')]:
            with self.subTest(code=code):
                data=deepcopy(self.data);data['findings'][0]['record_evidence']=[bad]
                with self.assertRaises(ContractError) as caught:self.parse(data)
                self.assertEqual(caught.exception.issue['code'],code)

    def test_model_authored_citation_objects_are_not_accepted(self):
        self.data['findings'][0]['record_evidence']=[{'source_id':'record-1','chunk_id':'1','quote':'Invented'}]
        with self.assertRaises(ValidationError):self.parse()

    def test_duplicate_or_missing_check_ids_are_rejected(self):
        for ids in [['CHECK_1','CHECK_1'],['OTHER']]:
            with self.subTest(ids=ids):
                data=deepcopy(self.data)
                data['findings']=[dict(data['findings'][0],check_id=value) for value in ids]
                with self.assertRaises(ContractError) as caught:self.parse(data)
                self.assertEqual(caught.exception.issue['code'],'checklist_coverage')

    def test_only_case_and_whole_json_wrapper_are_normalized(self):
        item=self.data['findings'][0]
        item.update(check_id='check_1',assessment='NEEDS_TRAINER_REVIEW',priority='LOW',record_evidence=[self.record_id.lower()])
        review=self.catalog.parse('```json\n'+json.dumps(self.data)+'\n```',['CHECK_1'])
        self.assertEqual(review.findings[0].check_id,'CHECK_1')
        validate_traceability(review,self.evidence)
        with self.assertRaises(ContractError):
            self.catalog.parse('Here is a review: '+json.dumps(self.data),['CHECK_1'])
        item['assessment']='looks okay'
        with self.assertRaises(ValidationError):self.parse()

    def test_unsent_staged_evidence_ids_are_not_accepted(self):
        registry=EvidenceCatalog([self.record,self.rule])
        rows,staged=registry.preview([{'source_id':self.record.id,'chunk_id':self.record.chunks[0].id,
                                     'text':self.record.chunks[0].text}])
        self.assertTrue(staged.entries)
        self.assertFalse(registry.entries)
        self.assertEqual(rows[0]['excerpts'][0]['evidence_id'],self.record_id)
        with self.assertRaises(ContractError):registry.parse(json.dumps(self.data),['CHECK_1'])

    def test_catalog_rejects_text_not_in_the_original_chunk(self):
        with self.assertRaises(ContractError):
            self.catalog.add([{'source_id':self.record.id,'chunk_id':self.record.chunks[0].id,'text':'Invented evidence'}])

    def test_schema_lists_ids_and_provides_soft_readability_targets(self):
        fields=self.catalog.schema(['CHECK_1'])['$defs']['DraftFinding']['properties']
        self.assertEqual(fields['check_id']['enum'],['CHECK_1'])
        self.assertEqual(fields['record_evidence']['items']['enum'],[self.record_id])
        self.assertEqual(fields['procedure_references']['items']['enum'],[self.rule_id])
        self.assertNotIn('maxLength',fields['feedback'])
        self.assertNotIn('maxLength=',fields['feedback']['description'])
        self.assertIn('longer explanations are allowed',fields['feedback']['description'])

    def test_repair_feedback_identifies_wrong_type_without_echoing_private_text(self):
        self.data['findings'][0]['feedback']=['PRIVATE_SOURCE_TEXT']
        with self.assertRaises(ValidationError) as caught:self.parse()
        issues=validation_issues(caught.exception,['CHECK_1'])
        self.assertEqual(issues[0]['path'],'findings.0.feedback')
        self.assertEqual(issues[0]['code'],'string_type')
        self.assertNotIn('PRIVATE_SOURCE_TEXT',json.dumps(issues))

    def test_long_feedback_survives_validation_without_truncation(self):
        for length in [601,2400,22000]:
            with self.subTest(length=length):
                text='Synthetic review detail. '+('a'*(length-24))
                self.data['findings'][0]['feedback']=text
                review=self.parse()
                validate_traceability(review,self.evidence)
                self.assertEqual(review.findings[0].feedback,text)

    def test_missing_citations_still_fail_final_traceability(self):
        self.data['findings'][0]['record_evidence']=[]
        review=self.parse()
        with self.assertRaises(ValueError) as caught:validate_traceability(review,self.evidence)
        self.assertEqual(validation_issues(caught.exception,['CHECK_1'])[0]['code'],'missing_citations')


if __name__=='__main__':unittest.main()
