import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app import Application
from config import DEFAULT_MODEL,DEFAULT_AUTH,ENVIRONMENT,PROVIDER,SETTINGS_VERSION,VERSION
from native_host import NativeService
from test_native import FakeVault
from test_app import MockProvider
class MigrationTests(unittest.TestCase):
    def current(self,**kwargs):
        return dict(settings_version=SETTINGS_VERSION,provider=PROVIDER,environment=ENVIRONMENT,model=DEFAULT_MODEL,auth_style=DEFAULT_AUTH,**kwargs)
    def test_old_development_and_anthropic_production_settings_migrate(self):
        for old in [{'environment':'development','settings_version':2}, {'environment':'production','settings_version':2}, {}]:
            with self.subTest(old=old),tempfile.TemporaryDirectory() as d:
                path=Path(d);vault=FakeVault();vault.token='old-token'
                saved=dict(old,model='anthropic.claude-opus-4-8',auth_style='x-api-key',downloads=str(path/'CustomDownloads'))
                (path/'settings.json').write_text(json.dumps(saved))
                with patch.dict('os.environ',{'MDT_GPT_MODEL':'stale-model','MDT_GPT_API_TOKEN':'old-process-token'}):
                    service=NativeService(path,MockProvider,vault,bundled_directory=None)
                try:
                    status=service.status();self.assertEqual(status['environment'],'production');self.assertEqual(status['model'],'gpt-5.6-terra')
                    self.assertEqual(status['auth_style'],'bearer');self.assertFalse(status['token_present']);self.assertEqual(vault.token,'')
                    self.assertEqual(status['downloads'],str(path/'CustomDownloads'))
                    stored=json.loads((path/'settings.json').read_text());self.assertEqual(stored['provider'],PROVIDER)
                    self.assertNotIn('old-token',json.dumps(stored));self.assertNotIn('opus48_verified',stored)
                finally:service.close()
    def test_current_scoped_token_is_retained(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);vault=FakeVault();vault.token='production-token'
            (path/'settings.json').write_text(json.dumps(self.current()))
            service=NativeService(path,MockProvider,vault,bundled_directory=None)
            try:self.assertEqual(service.app.connection['token'],'production-token')
            finally:service.close()
    def test_interrupted_migration_still_clears_vault_on_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);vault=FakeVault();vault.token='old-token'
            (path/'settings.json').write_text('{"environment":"development"}')
            app=Application(path,bundled_directory=None)
            try:self.assertTrue(json.loads((path/'settings.json').read_text())['reset_saved_token'])
            finally:app.pool.shutdown();app.repo.db.close()
            service=NativeService(path,MockProvider,vault,bundled_directory=None)
            try:self.assertEqual(vault.token,'')
            finally:service.close()
    def test_token_setup_saves_only_after_success_and_rejects_stale_settings(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);vault=FakeVault();service=NativeService(path,MockProvider,vault,bundled_directory=None)
            try:
                service.dispatch('token',{'token':'new-production-token','remember':True})
                self.assertEqual(vault.token,'new-production-token')
                self.assertNotIn('new-production-token',(path/'settings.json').read_text())
                for kwargs in [{'environment':'development'},{'model':'old-opus'},{'auth_style':'x-api-key'}]:
                    data=dict(model=DEFAULT_MODEL,auth_style=DEFAULT_AUTH,environment=ENVIRONMENT,downloads=str(path/'Downloads'));data.update(kwargs)
                    with self.assertRaises(ValueError):service.dispatch('settings',data)
                self.assertEqual(service.status()['model'],DEFAULT_MODEL)
            finally:service.close()
if __name__=='__main__':unittest.main()