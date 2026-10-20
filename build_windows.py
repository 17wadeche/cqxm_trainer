import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parent
PACKAGE = 'GCH-Check-My-Work-Windows-x64'
def bundle_command(work):
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--console', '--noupx', '--name', 'GCH-Helper',
               '--distpath', str(work/'output'), '--workpath', str(work/'temp'),
               '--specpath', str(work)]
    for asset in ('procedures', 'examples', 'web', 'review_prompt.md', 'native_config.json'):
        source = ROOT/asset
        target = asset if source.is_dir() else '.'
        command += ['--add-data', f'{source}:{target}']
    for package in ('docx', 'extract_msg', 'RTFDE'):
        command += ['--collect-all', package]
    command.append(str(ROOT/'windows_helper.py'))
    return command
def main():
    if sys.platform != 'win32' or platform.machine().lower() not in {'amd64', 'x86_64'} or sys.maxsize <= 2**32:
        raise SystemExit('Build this release on Windows x64 with 64-bit Python.')
    work = ROOT/'build/windows'
    output = ROOT/'dist'
    subprocess.run(bundle_command(work), cwd=ROOT, check=True)
    output.mkdir(exist_ok=True)
    destination = output/PACKAGE
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(work/'output/GCH-Helper', destination)
    for asset in ('extension', 'native_config.json', 'Install-Windows.cmd', 'Start-Windows.cmd',
                  'INSTALL_FOR_TRAINER.md', 'WINDOWS_RELEASE.md'):
        source = ROOT/asset
        if source.is_dir():
            shutil.copytree(source, destination/asset)
        else:
            shutil.copy2(source, destination/asset)
    subprocess.run([str(destination/'GCH-Helper.exe'), '--self-test'], cwd=destination, check=True)
    archive = Path(shutil.make_archive(str(output/PACKAGE), 'zip', output, PACKAGE))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'Release ZIP: {archive}')
if __name__ == '__main__':
    main()