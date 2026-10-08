"""The user's exact Production model must never be auto-substituted."""
import unittest
from config import DEFAULT_MODEL, ENVIRONMENT
from mdt import MDTClient, ProviderError, probe_connection
from responses_fixture import response
from test_gateway import rejected

class ExactModelTests(unittest.TestCase):
    def test_stale_model_environment_and_auth_rejected_before_network(self):
        for kwargs in [{'model':'anthropic.claude-opus-4-8'},{'model':'gpt-other'}, {'environment':'development'},
                       {'environment':'https://example.org'},{'auth_style':'x-api-key'}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ProviderError):
                MDTClient('secret',transport=lambda p:self.fail('must not connect'),**kwargs)

    def test_gateway_deployment_name_is_tracked_but_never_reused_as_request_id(self):
        calls=[]
        client=MDTClient('secret',transport=lambda p:calls.append(p) or response(model='internal-deployment-snapshot'))
        answer=client.message('test',[])
        probe_connection(client)
        self.assertEqual(answer['model'],'internal-deployment-snapshot')
        self.assertEqual(client.reported_models,{'internal-deployment-snapshot'})
        self.assertEqual({p['model'] for p in calls},{DEFAULT_MODEL})
        self.assertTrue(all(p['store'] is False for p in calls))
        self.assertEqual(client.context_usage[0]['reported_model'],'internal-deployment-snapshot')
        self.assertEqual(client.context_usage[0]['requested_model'],DEFAULT_MODEL)

    def test_invalid_model_metadata_is_rejected_without_echoing_it(self):
        for value in [{}, [], 'PRIVATE NAME WITH SPACES', 'secret', 'x'*161]:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ProviderError,'invalid model metadata') as e:
                    MDTClient('secret',transport=lambda p:response(model=value)).message('test',[])
                self.assertNotIn('PRIVATE',str(e.exception))

    def test_rejected_model_never_discovers_or_switches_models(self):
        calls=[]
        def transport(p):calls.append(p);raise rejected('Unknown model '+DEFAULT_MODEL)
        with self.assertRaisesRegex(ProviderError,'configured model'):
            probe_connection(MDTClient('secret',transport=transport),discover=True)
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['model'],DEFAULT_MODEL)

if __name__=='__main__':unittest.main()
