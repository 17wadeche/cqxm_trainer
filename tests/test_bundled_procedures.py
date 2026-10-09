import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import uuid4
from app import Application
from bundled_procedures import load_defaults
from config import BUNDLED_PROCEDURES
from ingest import source_from_bytes, extract
from models import extracted_digest
from native_host import NativeService
from repository import Repository
from test_app import MockProvider, encoded
from test_native import FakeVault
EXPECTED={'027-P043':'K','027-WI185':'R','027-WI186':'N','027-WI188':'M','054-P044':'L','054-WI198':'P'}
def replacement(docid='027-P043'):
    data=f'{docid}\nRevision TEST-UPDATE. Synthetic replacement for testing only; no actual procedure requirements.'.encode()
    return source_from_bytes('replacement.txt',data,str(uuid4()),'procedure',docid,revision='TEST-UPDATE',approved=True)
class BundledProcedureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        self.repo=Repository(self.path/'data')
    def tearDown(self):
        self.repo.db.close();self.temp.cleanup()
    def copy_bundle(self):
        return Path(shutil.copytree(BUNDLED_PROCEDURES,self.path/'bundle'))
    def test_exact_six_revisions_load_and_retrieval_uses_bundled_text(self):
        self.assertEqual(load_defaults(self.repo,BUNDLED_PROCEDURES),[])
        catalog=self.repo.catalog()
        self.assertEqual({s['document_id']:s['revision'] for s in catalog},EXPECTED)
        self.assertTrue(all(s['origin']=='bundled' for s in catalog))
        self.assertTrue(self.repo.search('complaint',[s['id'] for s in catalog]))
        for source,warnings in self.repo.active_procedures():
            self.assertEqual(extracted_digest(source.chunks),source.extracted_text_sha256)
            self.assertTrue(source.approved_revision)
            self.assertTrue(warnings)
    def test_cached_extraction_matches_all_original_pdfs(self):
        self.assertEqual(load_defaults(self.repo,BUNDLED_PROCEDURES),[])
        for source,_ in self.repo.active_procedures():
            original=(BUNDLED_PROCEDURES/source.name).read_bytes()
            self.assertEqual(hashlib.sha256(original).hexdigest(),source.file_sha256)
            chunks,_=extract(source.name,original)
            self.assertEqual(extracted_digest(chunks),source.extracted_text_sha256)
    def test_restart_does_not_duplicate_or_reactivate_old_defaults(self):
        load_defaults(self.repo,BUNDLED_PROCEDURES)
        original=self.repo.catalog()
        self.assertEqual(load_defaults(self.repo,BUNDLED_PROCEDURES),[])
        self.assertEqual(self.repo.catalog(),original)
        self.assertEqual(self.repo.db.execute('SELECT COUNT(*) FROM sources').fetchone()[0],6)
    def test_existing_uploaded_revision_wins_while_other_defaults_fill(self):
        source,warnings=replacement();self.repo.put(source,warnings)
        load_defaults(self.repo,BUNDLED_PROCEDURES)
        catalog={s['document_id']:s for s in self.repo.catalog()}
        self.assertEqual(len(catalog),6)
        self.assertEqual(catalog['027-P043']['id'],source.id)
        self.assertEqual(catalog['027-P043']['origin'],'uploaded')
        self.assertEqual(catalog['027-P043']['revision'],'TEST-UPDATE')
    def test_replacement_persists_and_previous_source_remains_in_history(self):
        load_defaults(self.repo,BUNDLED_PROCEDURES)
        old=next(s for s,_ in self.repo.active_procedures() if s.document_id=='027-P043')
        source,warnings=replacement();self.repo.put(source,warnings)
        self.repo.db.close();self.repo=Repository(self.path/'data')
        self.assertEqual(load_defaults(self.repo,BUNDLED_PROCEDURES),[])
        current=next(s for s in self.repo.catalog() if s['document_id']=='027-P043')
        self.assertEqual(current['id'],source.id)
        stored=self.repo.db.execute('SELECT active,payload FROM sources WHERE id=?',(old.id,)).fetchone()
        self.assertEqual(stored['active'],0)
        self.assertEqual(json.loads(stored['payload']),old.model_dump())
    def test_explicit_removal_is_not_undone_at_startup(self):
        load_defaults(self.repo,BUNDLED_PROCEDURES)
        self.repo.remove(self.repo.catalog()[0]['id'])
        self.assertEqual(load_defaults(self.repo,BUNDLED_PROCEDURES),[])
        self.assertEqual(len(self.repo.catalog()),5)
    def test_damaged_pdf_is_not_installed_but_other_defaults_are_available(self):
        bundle=self.copy_bundle();(bundle/'027-P043_K_EN.pdf').write_bytes(b'%PDF-damaged')
        errors=load_defaults(self.repo,bundle)
        self.assertEqual(len(errors),1);self.assertIn('027-P043',errors[0])
        self.assertEqual(len(self.repo.catalog()),5)
        shutil.copyfile(BUNDLED_PROCEDURES/'027-P043_K_EN.pdf',bundle/'027-P043_K_EN.pdf')
        self.assertEqual(load_defaults(self.repo,bundle),[])
        self.assertEqual(len(self.repo.catalog()),6)
    def test_bad_text_digest_and_wrong_revision_are_rejected(self):
        bundle=self.copy_bundle();index=bundle/'027-P043.json';original=index.read_text()
        for field in ['chunks','revision']:
            with self.subTest(field=field):
                value=json.loads(original)
                if field=='chunks':value['source']['chunks'][0]['text']='Altered source text'
                else:value['source']['revision']='WRONG'
                index.write_text(json.dumps(value))
                errors=load_defaults(self.repo,bundle)
                self.assertTrue(any('027-P043' in e for e in errors))
                self.assertFalse(any(s['document_id']=='027-P043' for s in self.repo.catalog()))
    def test_missing_bundle_returns_repair_message_instead_of_crashing(self):
        self.assertIn('Re-extract',load_defaults(self.repo,self.path/'missing')[0])
        self.assertEqual(self.repo.catalog(),[])
    def test_concurrent_upload_after_pending_read_is_preserved(self):
        other=Repository(self.path/'data')
        try:
            self.assertIn('027-P043',self.repo.defaults_pending())
            source,warnings=replacement();other.put(source,warnings)
            value=json.loads((BUNDLED_PROCEDURES/'027-P043.json').read_text())
            from models import EvidenceSource
            self.repo.install_defaults([(EvidenceSource.model_validate(value['source']),value['warnings'])])
            self.assertEqual(self.repo.catalog()[0]['id'],source.id)
        finally:other.db.close()
    def test_native_startup_and_user_upload_work_without_initial_document_setup(self):
        directory=self.path/'native';service=NativeService(directory,MockProvider,FakeVault())
        try:
            self.assertEqual(service.status()['missing_procedures'],[])
            self.assertEqual(service.status()['procedure_setup_errors'],[])
            source,_=replacement()
            result=service.dispatch('procedure',{'document_id':'027-P043','revision':'TEST-UPDATE','approved':True,
                'file':encoded('replacement.txt',source.chunks[0].text.encode())})
            current=next(s for s in result['procedures'] if s['document_id']=='027-P043')
            self.assertEqual(current['revision'],'TEST-UPDATE');self.assertEqual(current['origin'],'uploaded')
        finally:service.close()
        service=NativeService(directory,MockProvider,FakeVault())
        try:
            self.assertEqual(next(s['revision'] for s in service.status()['procedures'] if s['document_id']=='027-P043'),'TEST-UPDATE')
        finally:service.close()
    def test_manual_application_also_loads_defaults(self):
        app=Application(self.path/'manual',provider_factory=MockProvider)
        try:
            self.assertEqual(app.status()['procedure_count'],6)
            self.assertEqual(app.status()['procedure_setup_errors'],[])
        finally:app.pool.shutdown();app.repo.db.close()
class ReviewScopeTests(unittest.TestCase):
    def test_removed_documents_stay_excluded_from_new_reviews(self):
        from config import GROUPS, PROCEDURES
        with tempfile.TemporaryDirectory() as d:
            repo=Repository(Path(d))
            try:
                for docid in ['027-P043','D00788856','D00788854']:
                    source,warnings=source_from_bytes(docid+'.txt',(docid+' Synthetic test only; this text does not represent any controlled procedure requirements.').encode(),docid,'procedure',docid,revision='TEST',approved=True)
                    repo.put(source,warnings)
                self.assertEqual([s.document_id for s,_ in repo.active_procedures()],['027-P043'])
                allowed={d for d,_ in PROCEDURES}
                self.assertEqual(len(allowed),6)
                self.assertTrue(all(set(c[2])<=allowed for g in GROUPS for c in g['checks']))
                self.assertEqual(sum(len(g['checks']) for g in GROUPS),13)
            finally:repo.db.close()
if __name__=='__main__':unittest.main()