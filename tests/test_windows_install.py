import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import install_native
class WindowsInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()/'GCH & relocated (test) % folder'
        self.root.mkdir()
        self.extension = 'nlpgdigncphphoodneedoalppaeedapa'
        (self.root/'native_config.json').write_text(json.dumps({'extension_id': self.extension}))
    def test_portable_registration_uses_executable_without_python_launcher(self):
        executable = self.root/'GCH-Helper.exe'
        manifest_path = install_native.registration(self.root, executable, frozen=True)
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest['path'], str(executable))
        self.assertEqual(manifest['allowed_origins'], [f'chrome-extension://{self.extension}/'])
        self.assertEqual(manifest['type'], 'stdio')
        self.assertFalse((self.root/'native-launch.cmd').exists())
    def test_reinstall_replaces_stale_machine_registration(self):
        (self.root/'com.gch.check_my_work.json').write_text('{"path":"old-machine-python.exe"}')
        (self.root/'settings.json').write_text('preserve existing user settings')
        target = install_native.registration(self.root, self.root/'GCH-Helper.exe', frozen=True)
        self.assertNotIn('old-machine', target.read_text())
        self.assertEqual((self.root/'settings.json').read_text(), 'preserve existing user settings')
    def test_frozen_install_registers_external_exe_folder_not_internal_assets(self):
        registry = MagicMock()
        executable = self.root/'GCH-Helper.exe'
        with patch.object(install_native, 'os', SimpleNamespace(name='nt')), \
             patch.object(install_native.sys, 'frozen', True, create=True), \
             patch.object(install_native.sys, 'executable', str(executable)), \
             patch.dict('sys.modules', {'winreg': registry}):
            install_native.main()
        registry.CreateKey.assert_called_once_with(registry.HKEY_CURRENT_USER,
            r'Software\Google\Chrome\NativeMessagingHosts\com.gch.check_my_work')
        self.assertEqual(registry.SetValueEx.call_args.args[-1], str(self.root/'com.gch.check_my_work.json'))
        self.assertEqual(json.loads((self.root/'com.gch.check_my_work.json').read_text())['path'], str(executable))
    def test_source_install_still_launches_native_python_script(self):
        python = self.root/'developer Python % install/python.exe'
        target = install_native.registration(self.root, python)
        manifest = json.loads(target.read_text())
        launcher = self.root/'native-launch.cmd'
        self.assertEqual(manifest['path'], str(launcher))
        text = launcher.read_text()
        self.assertIn('"'+str(python).replace('%', '%%')+'"', text)
        self.assertIn('native_host.py" %*', text)
if __name__ == '__main__':
    unittest.main()
