"""Synthetic DER parsing, source identity, heading routing and full review flow."""
import json
from pathlib import Path
import tempfile
import threading
import unittest

from config import DEFAULT_MODEL, PROCEDURES, GROUPS
from engine import ReviewEngine
from ingest import source_from_bytes, verify_record
from models import Chunk, EvidenceSource, EvidenceManifest, Review, extracted_digest, validate_traceability
from record_sections import RecordIndex, embedded_mdrs
from repository import Repository
from test_app import MockProvider


def source(pages, offset=0):
    chunks=[Chunk(id=f'c{i}',locator=f'PDF page {i+offset}, part 1',text=t) for i,t in enumerate(pages,1)]
    return EvidenceSource(id='der-test',kind='record',name='Synthetic DER.pdf',document_id='DER',
        record_id='123456789',revision=None,approved_revision=False,file_sha256='a'*64,
        extracted_text_sha256=extracted_digest(chunks),chunks=chunks)


PAGES=[
    'Detailed Event Report\nProduct Event Transaction ID : 123456789\nSYNTHETIC ONLY',
    'Event Summary\nEvent ID 123456789\nEvent Status Re-Open\nProduct returned after initial closure.',
    'Investigation Summary\nEarlier no-return decision. Later reopened for product return.',
    'Regulatory Report Summary\nReport number 1111111-2026-01234\nForm Type MEDWATCH\nA. PATIENT INFORMATION',
    'Communication Summary\nSuccessful GFE Attempt # 001\nGFE Requirement for Follow-up 002',
    'EMDR\nReport number 1111111-2026-01234\nMessage Acknowledgment 3 Received Successful',
    'MEDWATCH importers, distributors and manufacturers\nMfr Report # 1111111-2026-01234\nA. PATIENT INFORMATION\nDate of This Report 03/12/2026',
    'MEDWATCH\nMfr Report # 1111111-2026-01234\nG. Type of Report\n[X] Initial\n[ ] Follow-up',
    'MEDWATCH\nMfr Report # 1111111-2026-01234\nA. PATIENT INFORMATION\nDate of This Report 09/02/2026',
    'MEDWATCH\nMfr Report # 1111111-2026-01234\nG. Type of Report\n[ ] Initial\n[X] Follow-up',
    'Product Analysis Report\nAnalysis ID: 999\nReturned segment analysis and dated conclusions.',
]


class DetailedReportTests(unittest.TestCase):
    def test_primary_auto_detects_der_and_pesr(self):
        for title,expected in [('Detailed Event Report','DER'),('Product Event Summary Report','PESR')]:
            s,_=source_from_bytes('report.txt',(title+'\nEvent ID: 123456789\nSynthetic complete report.').encode(),'r','record','PRIMARY','123456789')
            self.assertEqual(s.document_id,expected)

    def test_wrong_record_and_unrecognized_primary_are_rejected(self):
        for text in ['Detailed Event Report\nEvent ID 123456789\nEvent ID 987654321',
                     'Random document\nEvent ID 123456789\nUnrelated source material.']:
            with self.assertRaises(ValueError):source_from_bytes('test.txt',text.encode(),'r','record','PRIMARY','123456789')

    def test_blank_duplicate_label_and_zero_padded_line_item_are_supported(self):
        chunks=source([PAGES[0],'Duplicate SR/PE #\nConversion Related Data\nPE#: 0123456789-10\nEvent ID 123456789']).chunks
        verify_record(chunks,'123456789','DER')
        chunks.append(Chunk(id='bad',locator='page 99',text='Event ID 987654321'))
        with self.assertRaises(ValueError):verify_record(chunks,'123456789','DER')

    def test_headings_not_page_numbers_route_investigation(self):
        for shift in [0,45]:
            index=RecordIndex([source(PAGES,shift)])
            section=next(s for s in index.sections if s.kind=='investigation')
            self.assertEqual(section.chunks[0].locator,f'PDF page {3+shift}, part 1')
            candidates=index.candidates([('investigation','investigation',[],False)])
            self.assertIn(section,candidates)
            self.assertTrue(any(s.kind=='analysis_detail' for s in candidates))

    def test_linked_initial_and_followup_keep_original_locations(self):
        s=source(PAGES);forms,warnings=embedded_mdrs(s)
        self.assertEqual(len(forms),2);self.assertEqual(warnings,[])
        self.assertIn('initial MDR',forms[0].name);self.assertIn('follow-up MDR',forms[1].name)
        self.assertEqual(forms[0].chunks[0].locator,'PDF page 7, part 1')
        self.assertEqual(forms[1].file_sha256,s.file_sha256)
        self.assertEqual(forms[1].extracted_text_sha256,extracted_digest(forms[1].chunks))
        self.assertEqual(s.chunks[6].text,forms[0].chunks[0].text)

    def test_unlinked_form_and_mdr_mentions_do_not_qualify(self):
        pages=PAGES[:6]+[p.replace('1111111-2026-01234','2222222-2026-99999') for p in PAGES[6:]]
        forms,warnings=embedded_mdrs(source(pages))
        self.assertEqual(forms,[]);self.assertEqual(len(warnings),2)
        index=RecordIndex([source(PAGES[:6])])
        self.assertFalse(any(s.kind=='mdr' for s in index.sections))

    def test_section_reads_are_bounded_and_scoped(self):
        index=RecordIndex([source(PAGES)]);section=next(s for s in index.sections if s.kind=='mdr')
        rows,page=index.read(section.source_id,section.id,0,1)
        self.assertEqual(len(rows),1);self.assertEqual(page['next_offset'],1)
        rows,page=index.read(section.source_id,section.id,1,1)
        self.assertIsNone(page['next_offset'])
        with self.assertRaises(ValueError):index.read('wrong-source',section.id)

    def test_full_review_runs_mdr_consistency_and_saves_coverage(self):
        # Separate pages via an in-memory PDF to exercise the normal entry point.
        import io
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        data=io.BytesIO();pdf=PdfWriter()
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        for page in PAGES:
            p=pdf.add_blank_page(612,792)
            p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            commands=['BT /F1 10 Tf 35 750 Td 14 TL']
            for line in page.splitlines():commands.append('('+line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')+') Tj T*')
            stream=DecodedStreamObject();stream.set_data(('\n'.join(commands)+'\nET').encode())
            p[NameObject('/Contents')]=stream
        pdf.write(data)
        with tempfile.TemporaryDirectory() as directory:
            repo=Repository(Path(directory))
            try:
                for docid,_ in PROCEDURES:
                    s,w=source_from_bytes(docid+'.txt',(docid+'\nSynthetic identifier rule only.').encode(),docid,'procedure',docid,revision='TEST',approved=True)
                    repo.put(s,w)
                result=ReviewEngine(repo,MockProvider).run('test-der','123456789','Re-Open','Synthetic only',
                    [('PRIMARY','DER.pdf',data.getvalue())],{'token':'fake','model':DEFAULT_MODEL,'auth_style':'bearer'},lambda *args:None,threading.Event())
                review=Review.model_validate(result['review'])
                self.assertEqual(len(review.findings),13)
                consistency=next(f for f in review.findings if f.check_id=='consistency')
                self.assertEqual(consistency.assessment,'needs_trainer_review')
                out=Path(directory)/'reports/test-der'
                evidence=EvidenceManifest.model_validate_json((out/'evidence.json').read_text())
                self.assertEqual(sum(s.document_id=='MDR' for s in evidence.sources),2)
                validate_traceability(review,evidence)
                self.assertTrue(json.loads((out/'retrieval_coverage.json').read_text()))
                self.assertTrue((out/'review.docx').read_bytes().startswith(b'PK'))
                consistency.record_evidence=consistency.record_evidence[:1]
                with self.assertRaisesRegex(ValueError,'event and MDR evidence'):validate_traceability(review,evidence)
            finally:repo.db.close()


if __name__=='__main__':unittest.main()
