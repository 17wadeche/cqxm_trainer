"""Background helper tests use synthetic sources and a mock MDT provider."""
import base64
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest

from native_host import NativeService, allowed_origin, encode_message, read_message, MAX_IN
from config import PROCEDURES, ROOT
from test_app import MockProvider, PESR, encoded


class FakeVault:
    supported = True
    def __init__(self): self.token = ''
    def load(self): return self.token
    def save(self, token): self.token = token
    def clear(self): self.token = ''


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.vault = FakeVault()
        self.service = NativeService(self.directory, MockProvider, self.vault, bundled_directory=None)
        self.service.app.downloads = self.directory/'Downloads'
        self.service.app.downloads.mkdir()

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def configure(self):
        self.service.dispatch('token', {'token':'synthetic-test-secret','remember':True})
        for docid,_ in PROCEDURES[:6]:
            content=f'{docid} revision TEST ONLY\nUse the supplied event identifier for this synthetic exercise. No real procedure is represented.\n'.encode()
            self.service.dispatch('procedure', {'document_id':docid,'revision':'TEST','approved':True,'file':encoded(docid+'.txt',content)})

    def test_binary_protocol_handles_unicode_and_rejects_oversize(self):
        value={'id':1,'message':'é → ready'}
        self.assertEqual(read_message(io.BytesIO(encode_message(value))),value)
        self.assertIsNone(read_message(io.BytesIO()))
        with self.assertRaises(ValueError):read_message(io.BytesIO(struct.pack('=I',MAX_IN+1)))
        with self.assertRaises(EOFError):read_message(io.BytesIO(b'\x10\x00'))

    def test_all_six_references_required_for_one_click_review(self):
        self.service.dispatch('token',{'token':'synthetic-test-secret','remember':False})
        with self.assertRaisesRegex(ValueError,'six training procedures'):
            self.service.dispatch('capture_start',{'record_id':'TRAIN-001','stage':'Intake'})

    def test_token_stays_out_of_status_and_plaintext_settings(self):
        result=self.service.dispatch('token',{'token':'synthetic-test-secret','remember':True})
        self.assertTrue(result['token_present'])
        self.assertNotIn('synthetic-test-secret',json.dumps(result))
        self.assertEqual(self.vault.token,'synthetic-test-secret')
        self.service.dispatch('clear_token',{})
        self.assertFalse(self.service.status()['token_present'])
        self.assertEqual(self.vault.token,'')

    def test_capture_review_and_automatic_word_save_once(self):
        self.configure()
        lease=self.service.dispatch('capture_start',{'record_id':'TRAIN-001','stage':'Intake'})
        report=self.service.app.downloads/'PESR.txt';report.write_bytes(PESR)
        job=self.service.dispatch('capture_complete',{'capture_id':lease['capture_id'],'path':str(report)})
        limit=time.monotonic()+10
        while time.monotonic()<limit:
            state=self.service.dispatch('job',job)
            if state['status'] in {'ready','failed'}:break
            time.sleep(.01)
        self.assertEqual(state['status'],'ready',state)
        self.assertTrue((self.service.app.downloads/state['filename']).read_bytes().startswith(b'PK'))
        second=self.service.dispatch('job',job)
        self.assertEqual(second['filename'],state['filename'])
        self.assertEqual(len(list(self.service.app.downloads.glob('*.docx'))),1)
        self.assertNotIn('result',state)  # Large evidence never travels through native replies.
    def test_incoming_capture_flows_through_native_helper_to_cited_word_report(self):
        from test_attachments import IncomingProvider, INCOMING
        self.configure()
        self.service.app.engine.provider_factory=IncomingProvider
        lease=self.service.dispatch('capture_start',{'record_id':'TRAIN-001','stage':'Intake'})
        incoming=self.service.app.downloads/'patient.txt';incoming.write_bytes(INCOMING)
        self.service.dispatch('capture_attachment',{'capture_id':lease['capture_id'],'path':str(incoming)})
        report=self.service.app.downloads/'PESR.txt';report.write_bytes(PESR)
        job=self.service.dispatch('capture_complete',{'capture_id':lease['capture_id'],'path':str(report),'attachment_limits':[]})
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            status=self.service.dispatch('job',job)
            if status['status'] in {'ready','failed'}:break
            time.sleep(.01)
        self.assertEqual(status['status'],'ready',status)
        output=self.directory/'reports'/job['id']
        evidence=json.loads((output/'evidence.json').read_text())
        incoming_source=next(s for s in evidence['sources'] if s['document_id']=='ATTACHMENT')
        review=json.loads((output/'review.json').read_text())
        narrative=next(f for f in review['findings'] if f['check_id']=='narrative')
        self.assertTrue(any(ref['source_id']==incoming_source['id'] for ref in narrative['record_evidence']))
        self.assertTrue((self.service.app.downloads/status['filename']).is_file())
    def test_open_report_cannot_open_an_arbitrary_path(self):
        with self.assertRaisesRegex(ValueError,'no longer available'):
            self.service.dispatch('open_report',{'id':'../../../other.exe'})

    def test_native_origin_is_pinned_to_this_extension(self):
        extension=json.loads((ROOT/'native_config.json').read_text())['extension_id']
        self.assertTrue(allowed_origin('chrome-extension://'+extension+'/'))
        self.assertFalse(allowed_origin('https://crm.medtronic.com/'))
        self.assertFalse(allowed_origin('chrome-extension://'+'a'*32+'/'))

    def test_no_arbitrary_native_commands(self):
        with self.assertRaisesRegex(ValueError,'Unknown command'):
            self.service.dispatch('execute',{'command':'anything'})

    def test_actual_host_stdio_round_trip_without_a_window(self):
        extension=json.loads((ROOT/'native_config.json').read_text())['extension_id']
        env=dict(os.environ,GCH_DATA_DIR=str(self.directory/'protocol'))
        env.pop('MDT_GPT_API_TOKEN',None)
        result=subprocess.run([sys.executable,str(ROOT/'native_host.py'),'chrome-extension://'+extension+'/'],
            input=encode_message({'id':3,'method':'status','data':{}}),capture_output=True,env=env,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        reply=read_message(io.BytesIO(result.stdout))
        self.assertTrue(reply['ok'])
        self.assertEqual(reply['id'],3)
        self.assertFalse(reply['result']['token_present'])


if __name__=='__main__':unittest.main()
