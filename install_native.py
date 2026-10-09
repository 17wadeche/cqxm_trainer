import json
import os
from pathlib import Path
import sys
def main():
    if os.name != 'nt':
        raise SystemExit('This installer is for Windows.')
    import winreg
    root = Path(__file__).resolve().parent
    cfg = json.loads((root/'native_config.json').read_text())
    def literal(value):
        return str(value).replace('%', '%%')
    launcher = root/'native-launch.cmd'
    launcher.write_text('@echo off\r\nchcp 65001 >nul\r\n"'+literal(sys.executable)+'" "'+literal(root/'native_host.py')+'" %*\r\n', encoding='utf-8', newline='')
    target = root/'com.gch.check_my_work.json'
    target.write_text(json.dumps({'name':'com.gch.check_my_work', 'description':'GCH Check my work background helper',
        'path':str(launcher), 'type':'stdio',
        'allowed_origins':['chrome-extension://'+cfg['extension_id']+'/']}, indent=2), encoding='utf-8')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Google\Chrome\NativeMessagingHosts\com.gch.check_my_work') as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(target))
    print('Background helper installed. It will start automatically from GCH.')
    print('Load the extension folder in Chrome once, then reload GCH.')
if __name__ == '__main__':
    main()
