"""Production Responses wire contract, validation and explicit fallbacks."""
import io
import json
import socket
import ssl
import unittest
from copy import deepcopy
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from config import DEFAULT_AUTH, DEFAULT_MODEL, ENDPOINT
from mdt import MDTClient, ProviderError, probe_connection, response_text
from responses_fixture import response, wire_response

TOOLS=[{'name':'read_section','description':'Read supplied evidence','input_schema':{'type':'object','properties':{'source_id':{'type':'string'}},'required':['source_id'],'additionalProperties':False}}]
SCHEMA={'type':'object','properties':{'status':{'type':'string'}},'required':['status'],'additionalProperties':False}

def rejected(message,status=400):
    return HTTPError(ENDPOINT,status,'Rejected',{'request-id':'test-request'},io.BytesIO(json.dumps({'error':{'message':message}}).encode()))

class GatewayTests(unittest.TestCase):
    def test_actual_http_uses_exact_production_route_model_and_bearer(self):
        seen=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(response()).encode()
        class Opener:
            def open(self,req,timeout):seen.append(req);return Response()
        with patch('urllib.request.build_opener',return_value=Opener()):
            MDTClient('secret',DEFAULT_MODEL).message('Test',[{'role':'user','content':'hello'}],tools=TOOLS,schema=SCHEMA)
        self.assertEqual(DEFAULT_AUTH,'bearer')
        self.assertEqual(seen[0].full_url,'https://api.gpt.medtronic.com/providers/openai/v1/responses')
        self.assertEqual(seen[0].get_header('Authorization'),'Bearer secret')
        self.assertIsNone(seen[0].get_header('X-api-key'));self.assertIsNone(seen[0].get_header('Anthropic-version'))
        p=json.loads(seen[0].data)
        self.assertEqual(p['model'],'gpt-5.6-terra');self.assertFalse(p['store'])
        self.assertEqual(p['input'][0],{'role':'system','content':'Test'})
        self.assertEqual(p['text']['format']['type'],'json_schema');self.assertEqual(p['tool_choice'],'none')
        self.assertEqual(p['tools'][0]['type'],'function')
        self.assertTrue(p['tools'][0]['strict'])
        for key in ['messages','system','max_tokens','output_config','temperature']:self.assertNotIn(key,p)

    def test_documented_gateway_output_without_status_and_usage_aliases(self):
        value=response();value.pop('status');value.pop('model')
        value['usage']={'prompt_tokens':123,'completion_tokens':45,'total_tokens':168}
        client=MDTClient('secret',transport=lambda p:value)
        self.assertEqual(response_text(client.message('test',[])),'{"status":"ok"}')
        self.assertEqual(client.usage,{'input_tokens':123,'output_tokens':45})

    def test_probes_text_then_json_without_records(self):
        seen=[]
        client=MDTClient('secret',transport=lambda p:seen.append(p) or response())
        self.assertEqual(probe_connection(client),{'model':DEFAULT_MODEL,'structured_mode':'native'})
        self.assertNotIn('text',seen[0]);self.assertIn('text',seen[1])
        self.assertNotIn('tools',seen[0]);self.assertEqual(len(seen),2)

    def test_explicit_format_rejection_falls_back_same_host_model(self):
        seen=[]
        def transport(p):
            seen.append(p)
            if 'text' in p:raise rejected("Unknown parameter: 'text'")
            return response()
        client=MDTClient('secret',transport=transport)
        self.assertEqual(probe_connection(client)['structured_mode'],'validated_json')
        self.assertEqual(len(seen),3)
        self.assertIn('Return only a JSON object',seen[-1]['input'][0]['content'])
        self.assertEqual({p['model'] for p in seen},{DEFAULT_MODEL})
        self.assertTrue(all(p['store'] is False for p in seen))

    def test_invalid_schema_unexplained_error_and_auth_never_fall_back(self):
        for error in [('text.format invalid schema unsupported type',400),('Request rejected',400),('Invalid token secret',401),('Denied',403)]:
            with self.subTest(error=error):
                seen=[]
                def transport(p):seen.append(p);raise rejected(*error)
                with self.assertRaises(ProviderError):MDTClient('secret',transport=transport).message('test',[],schema=SCHEMA)
                self.assertEqual(len(seen),1)

    def test_explicit_tools_rejection_uses_bounded_read_only_json_plan(self):
        seen=[]
        def transport(p):
            seen.append(p)
            if 'tools' in p:raise rejected('tools is not supported')
            return response(json.dumps({'tool_calls':[{'name':'read_section','arguments':{'source_id':'s1'}}],'text':''}))
        client=MDTClient('secret',transport=transport)
        answer=client.message('retrieve',[],tools=TOOLS)
        self.assertEqual(client.tool_mode,'validated_json');self.assertEqual(len(seen),2)
        call=answer['content'][0];self.assertEqual(call['type'],'tool_use');self.assertEqual(call['input'],{'source_id':'s1'})
        self.assertNotIn('tools',seen[-1]);self.assertNotIn('include',seen[-1])
        self.assertIn('RETRIEVAL PROTOCOL',seen[-1]['input'][0]['content'])
        # Continuations use text transcripts, not orphan native call IDs.
        client.transport=lambda p:seen.append(p) or response('{"tool_calls":[],"text":"READY"}')
        client.message('retrieve',[{'role':'assistant','content':answer['content']},{'role':'user','content':[{'type':'tool_result','tool_use_id':call['id'],'content':'known source'}]}],tools=TOOLS)
        self.assertTrue(all('role' in i for i in seen[-1]['input']))

    def test_portable_plan_cannot_request_arbitrary_tools(self):
        client=MDTClient('secret',transport=lambda p:response('{"tool_calls":[{"name":"send_email","arguments":{}}],"text":""}'))
        client.tool_mode='validated_json'
        with self.assertRaisesRegex(ProviderError,'invalid retrieval plan'):client.message('test',[],tools=TOOLS)

    def test_replays_reasoning_call_and_matching_output_without_loss(self):
        output=[{'type':'reasoning','id':'rs1','summary':[],'encrypted_content':'OPAQUE'},
                {'type':'function_call','id':'fc1','call_id':'c1','name':'read_section','arguments':'{"source_id":"s1"}','status':'completed'}]
        seen=[]
        client=MDTClient('secret',transport=lambda p:seen.append(deepcopy(p)) or {'output':output,'status':'completed'})
        answer=client.message('test',[{'role':'user','content':'read it'}],tools=TOOLS)
        client.transport=lambda p:seen.append(deepcopy(p)) or response('READY')
        client.message('test',[{'role':'user','content':'read it'},{'role':'assistant','content':answer['content']},
            {'role':'user','content':[{'type':'tool_result','tool_use_id':'c1','content':'evidence'}]}],tools=TOOLS)
        self.assertEqual(seen[-1]['input'][2:4],output)
        self.assertEqual(seen[-1]['input'][4],{'type':'function_call_output','call_id':'c1','output':'evidence'})
        self.assertNotIn('previous_response_id',seen[-1])

    def test_function_calls_in_final_or_unknown_tool_or_bad_args_are_rejected(self):
        for name,args,schema in [('read_section','{}',SCHEMA),('send_email','{}',None),('read_section','invalid',None)]:
            client=MDTClient('secret',transport=lambda p:{'output':[{'type':'function_call','call_id':'x','name':name,'arguments':args}]})
            with self.assertRaises(ProviderError):client.message('test',[],tools=TOOLS,schema=schema)

    def test_partial_failed_refused_and_nonresponses_envelopes_are_rejected(self):
        values=[{'content':[{'type':'text','text':'unsafe'}]},dict(response(),status='in_progress'),
                dict(response(),status='failed',error={'message':'PRIVATE'}),
                dict(response(),status='incomplete',incomplete_details={'reason':'content_filter'}),
                {'output':[{'type':'message','status':'incomplete','content':[{'type':'output_text','text':'PRIVATE'}]}]},
                {'output':[{'type':'message','content':[{'type':'refusal','refusal':'PRIVATE'}]}]}]
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(ProviderError) as e:MDTClient('secret',transport=lambda p:value).message('test',[])
                self.assertNotIn('PRIVATE',str(e.exception))

    def test_no_redirect_or_token_leak_and_clear_network_categories(self):
        from mdt import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.invalid'))
        for reason,expected in [(socket.gaierror(),'DNS'),(ssl.SSLCertVerificationError(),'certificate'),(TimeoutError(),'timed out'),(ssl.SSLEOFError(),'interrupted')]:
            def transport(p):raise URLError(reason)
            with self.assertRaises(ProviderError) as e:MDTClient('secret',transport=transport).message('test',[])
            self.assertIn(expected,str(e.exception));self.assertNotIn('secret',str(e.exception))

    def test_invalid_json_probe_fails_and_diagnostics_redact_credentials(self):
        with self.assertRaisesRegex(ProviderError,'failed local validation'):
            probe_connection(MDTClient('secret',transport=lambda p:response('not json')))
        def transport(p):raise rejected('Invalid Authorization: Bearer secret',401)
        with self.assertRaises(ProviderError) as e:probe_connection(MDTClient('secret',transport=transport))
        self.assertNotIn('secret',str(e.exception));self.assertIn('credential removed',str(e.exception))

if __name__=='__main__':unittest.main()
