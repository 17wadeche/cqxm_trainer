import io
import unittest
from urllib.error import HTTPError
from config import DEFAULT_MODEL, ENDPOINT
from context_budget import estimate_tokens, fits_context
from mdt import MDTClient, ProviderError
from responses_fixture import wire_response
def response():
    return wire_response({'content':[{'type':'text','text':'READY'}],'stop_reason':'end_turn','model':DEFAULT_MODEL,
            'usage':{'input_tokens':15000,'output_tokens':20}})
class ContextTests(unittest.TestCase):
    def test_larger_than_old_byte_limit_fits_with_output_room(self):
        seen=[]
        client=MDTClient('fake',DEFAULT_MODEL,transport=lambda p:seen.append(p) or response())
        client.message('Test',[{'role':'user','content':'x'*90000}],max_tokens=8192)
        self.assertEqual(len(seen),1)
        self.assertEqual(client.context_usage[0]['method'],'estimated')
        self.assertLess(client.context_usage[0]['input_budget'],60000)
    def test_full_responses_input_tools_and_schema_are_counted_before_sending(self):
        client=MDTClient('fake',DEFAULT_MODEL,transport=lambda p:self.fail('Must not send oversized input'))
        with self.assertRaises(ProviderError) as e:
            client.message('PRIVATE SOURCE '+'x'*210000,[],max_tokens=16384)
        self.assertEqual(e.exception.stop_reason,'local_context_budget')
        self.assertNotIn('PRIVATE',str(e.exception))
    def test_usage_calibrates_estimate_upward_without_extra_count_route(self):
        seen=[]
        client=MDTClient('fake',DEFAULT_MODEL,transport=lambda p:seen.append(p) or response())
        client.message('Instructions',[{'role':'user','content':'Evidence'}],schema={'type':'object'})
        self.assertEqual(len(seen),1)
        self.assertEqual(client.context_usage[0]['reported_input'],15000)
        self.assertGreater(client.estimate_scale,1)
        self.assertIn('input',seen[0]);self.assertIn('text',seen[0])
    def test_unicode_and_reserved_output_are_accounted_for(self):
        self.assertGreater(estimate_tokens('漢'*100),estimate_tokens('a'*100))
        self.assertFalse(fits_context(96001,8192))
        self.assertFalse(fits_context(95000,30000))
        self.assertTrue(fits_context(60000,16384))
    def test_explicit_gateway_input_overflow_is_distinct_and_redacted(self):
        import json
        def transport(payload):
            raise HTTPError(ENDPOINT,400,'Invalid',{},io.BytesIO(json.dumps({'error':{'message':'prompt is too long PRIVATE_RECORD'}}).encode()))
        client=MDTClient('fake',DEFAULT_MODEL,transport=transport)
        with self.assertRaises(ProviderError) as error:client.message('Test',[])
        self.assertEqual(error.exception.stop_reason,'input_context_budget')
        self.assertNotIn('PRIVATE_RECORD',str(error.exception))
    def test_full_review_restarts_an_oversized_batch_with_a_fresh_smaller_packet(self):
        import json,tempfile,threading
        from pathlib import Path
        from config import PROCEDURES
        from engine import ReviewEngine
        from ingest import source_from_bytes
        from repository import Repository
        from test_app import MockProvider
        lengths=[]
        class OverflowOnce(MockProvider):
            def message(self,system,messages,**kwargs):
                lengths.append(len(json.dumps(messages)))
                if len(lengths)==1:raise ProviderError('Synthetic input overflow',stop_reason='input_context_budget')
                return super().message(system,messages,**kwargs)
        with tempfile.TemporaryDirectory() as directory:
            repo=Repository(Path(directory))
            try:
                for docid,_ in PROCEDURES:
                    data=(docid+'\n'+('Synthetic identifier intake event complaint determination. '*650)).encode()
                    s,w=source_from_bytes('rule.txt',data,docid,'procedure',docid,revision='TEST',approved=True)
                    repo.put(s,w)
                data=b'Product Event Summary Report\nEvent ID: TRAIN-001\nSynthetic training record.'
                result=ReviewEngine(repo,OverflowOnce).run('test','TRAIN-001','Intake','Synthetic only',
                    [('PRIMARY','PESR.txt',data)],{'token':'fake','model':DEFAULT_MODEL,'auth_style':'bearer'},lambda *a:None,threading.Event())
                self.assertEqual(len(result['review']['findings']),13)
                self.assertLess(lengths[1],lengths[0])
            finally:repo.db.close()
if __name__=='__main__':unittest.main()