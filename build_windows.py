import argparse
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from package_token import read_token_file, write_token_file
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--include-token', action='store_true',
                        help='Include only MDT_GPT_API_TOKEN from the source .env in the release.')
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().lower() not in {'amd64', 'x86_64'} or sys.maxsize <= 2**32:
        raise SystemExit('Build this release on Windows x64 with 64-bit Python.')
    token = read_token_file(ROOT/'.env') if args.include_token else ''
    if args.include_token and not token:
        raise SystemExit('--include-token requires MDT_GPT_API_TOKEN in the source .env file.')
    build_root = ROOT/'build/windows'
    build_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='run-', dir=build_root))
    output = ROOT/'dist'
    output.mkdir(exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix=PACKAGE+'-', dir=output))
    subprocess.run(bundle_command(work), cwd=ROOT, check=True)
    shutil.copytree(work/'output/GCH-Helper', destination, dirs_exist_ok=True)
    for asset in ('extension', 'native_config.json', 'Install-Windows.cmd', 'Start-Windows.cmd',
                  'INSTALL_FOR_TRAINER.md', 'WINDOWS_RELEASE.md'):
        source = ROOT/asset
        if source.is_dir():
            shutil.copytree(source, destination/asset)
        else:
            shutil.copy2(source, destination/asset)
    subprocess.run([str(destination/'GCH-Helper.exe'), '--self-test'], cwd=destination, check=True)
    if args.include_token:
        write_token_file(destination/'.env', token)
    archive = Path(shutil.make_archive(str(destination), 'zip', output, destination.name))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'Release folder: {destination}')
    print(f'Release ZIP: {archive}')
    if args.include_token:
        print('This release contains the shared MDT token in .env; distribute it accordingly.')
if __name__ == '__main__':
    main()