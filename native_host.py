"""Chrome starts this stdio helper automatically; it has no app window or port."""
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app import Application, checked_text, file_payload
from config import ROOT, PROCEDURES, DEFAULT_MODEL, DEFAULT_AUTH, ENVIRONMENT, VERSION, BUNDLED_PROCEDURES, data_directory
from ingest import source_from_bytes
from mdt import ProviderError, probe_connection
from token_store import TokenStore

MAX_IN = 30 * 1024 * 1024
MAX_OUT = 900 * 1024
HOST_NAME = 'com.gch.check_my_work'


def read_exact(stream, length):
    parts = bytearray()
    while len(parts) < length:
        value = stream.read(length - len(parts))
        if not value:
            raise EOFError()
        parts.extend(value)
    return bytes(parts)


def read_message(stream):
    prefix = stream.read(4)
    if not prefix:
        return None
    if len(prefix) < 4:
        prefix += read_exact(stream, 4-len(prefix))
    length = struct.unpack('=I', prefix)[0]
    if not 0 < length <= MAX_IN:
        raise ValueError('Message too large')
    message = json.loads(read_exact(stream, length))
    if not isinstance(message, dict):
        raise ValueError('Expected an object')
    return message


def encode_message(value):
    raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
    if len(raw) > MAX_OUT:
        raise ValueError('Response too large')
    return struct.pack('=I', len(raw)) + raw


class NativeService:
    def __init__(self, directory, provider_factory=None, token_store=None, *, bundled_directory=BUNDLED_PROCEDURES):
        kwargs = {'bundled_directory':bundled_directory}
        if provider_factory:kwargs['provider_factory']=provider_factory
        self.app = Application(directory, **kwargs)
        self.vault = token_store or TokenStore(directory)
        if self.app.reset_saved_token:
            self.vault.clear()
            self.app.connection['token'] = ''
            self.app.reset_saved_token = False
            self.app.persist_preferences()
        if not self.app.connection['token']:
            self.app.connection['token'] = self.vault.load()
        self.lock = threading.RLock()
        self.saved = {}

    def status(self):
        sources = self.app.repo.catalog()
        return {'version':VERSION, 'token_present': bool(self.app.connection['token']),
                'remember_supported': self.vault.supported,
                'missing_procedures': [d for d, _ in PROCEDURES[:6]
                                       if d not in {p['document_id'] for p in sources}],
                'procedures': sources, 'model': self.app.connection['model'],
                'procedure_setup_errors': self.app.procedure_setup_errors,
                'auth_style': self.app.connection['auth_style'],
                'environment':ENVIRONMENT,
                'downloads': str(self.app.downloads),
                'expected_procedures': [{'id': d, 'name': n} for d, n in PROCEDURES]}

    def ready(self):
        state = self.status()
        if not state['token_present']:
            raise ValueError('Enter your MDT-GPT token to continue.')
        if state['missing_procedures']:
            raise ValueError('Your trainer needs to add the six training procedures before you can check your work.')

    def verify_token(self, data):
        token = checked_text(data.get('token'), 'your MDT-GPT token', 8192)
        if '\r' in token or '\n' in token:
            raise ValueError('Paste the token as a single line.')
        cfg = self.app.connection
        environment = ENVIRONMENT
        if data.get('environment', ENVIRONMENT) != ENVIRONMENT:
            raise ValueError('This build only connects to MDT-GPT Production.')
        client = self.app.provider_factory(token, cfg['model'], cfg['auth_style'], environment=environment)
        result = probe_connection(client, discover=True)
        with self.lock:
            if data.get('remember') is True:
                self.vault.save(token)
            else:
                self.vault.clear()
            cfg.update(token=token, tested=True, environment=environment, **result)
            self.app.persist_preferences()
        return self.status()

    def job_status(self, job_id):
        job = self.app.get_job(job_id)
        result = {k:job[k] for k in ['id','record_id','status','progress','message','error']}
        if job['status'] == 'failed' and (job['error'] or '').startswith('MDT-GPT rejected the token.'):
            with self.lock:
                self.app.connection.update(token='', tested=False)
                self.vault.clear()
            result['needs_token'] = True
            result['remember_supported'] = self.vault.supported
            result['environment'] = ENVIRONMENT
        if job['status'] == 'ready':
            with self.lock:
                if job_id not in self.saved:
                    origin = self.app.directory/'reports'/job_id/'review.docx'
                    self.app.downloads.mkdir(parents=True, exist_ok=True)
                    target = self.app.downloads/f"GCH_Review_{job['record_id']}_{job_id[:8]}.docx"
                    # Unique report name; exclusive create never overwrites another file.
                    with target.open('xb') as output, origin.open('rb') as source:
                        shutil.copyfileobj(source, output)
                    self.saved[job_id] = target
                result['filename'] = self.saved[job_id].name
            findings = job['result']['review']['findings']
            result['needs_evidence'] = sum(f['assessment']=='not_assessable' for f in findings)
        return result

    def dispatch(self, method, data):
        if not isinstance(data, dict):
            raise ValueError('Invalid request')
        if method == 'status':
            return self.status()
        if method == 'token':
            return self.verify_token(data)
        if method == 'clear_token':
            with self.lock:
                self.app.connection.update(token='', tested=False)
                self.vault.clear()
            return {'ok':True}
        if method == 'settings':
            model = checked_text(data.get('model'), 'the MDT-GPT model ID', 120)
            if model != DEFAULT_MODEL:
                raise ValueError('This build uses '+DEFAULT_MODEL+'.')
            style = data.get('auth_style', DEFAULT_AUTH)
            if style != DEFAULT_AUTH:
                raise ValueError('Use Authorization: Bearer for the Production Responses API.')
            environment = ENVIRONMENT
            if data.get('environment', ENVIRONMENT) != ENVIRONMENT:
                raise ValueError('This build only connects to MDT-GPT Production.')
            folder = Path(checked_text(data.get('downloads'), 'the Downloads folder', 1024)).expanduser().resolve()
            if folder == Path(folder.anchor) or folder == Path.home().resolve():
                raise ValueError('Choose the Downloads folder, not the drive root or home folder.')
            with self.lock:
                if environment != self.app.connection['environment']:
                    self.vault.clear()
                    self.app.connection['token'] = ''
                self.app.connection.update(model=model, auth_style=style, environment=environment,
                                           tested=False, structured_mode='auto')
                self.app.downloads = folder
                self.app.persist_preferences()
            return self.status()
        if method == 'procedure':
            document_id = checked_text(data.get('document_id'), 'the document ID', 40)
            if document_id not in {i for i, _ in PROCEDURES} or data.get('approved') is not True:
                raise ValueError('Choose the controlled procedure and confirm its approved revision.')
            revision = checked_text(data.get('revision'), 'the revision', 80)
            name, payload = file_payload(data.get('file'))
            source, warnings = source_from_bytes(name, payload, str(uuid4()), 'procedure', document_id,
                                                 revision=revision, approved=True)
            normalized = re.sub(r'\W','', '\n'.join(c.text for c in source.chunks)).upper()
            if re.sub(r'\W','',document_id).upper() not in normalized:
                raise ValueError('The selected document ID was not found in this file.')
            self.app.repo.put(source, warnings)
            return self.status()
        if method == 'capture_start':
            self.ready()
            return self.app.capture_start(data)
        if method == 'capture_cancel':
            with self.app.lock:
                self.app.captures.pop(data.get('capture_id'), None)
            return {'ok':True}
        if method == 'capture_complete':
            self.ready()
            job = self.app.capture_complete(data.get('capture_id'), data)
            return {'id':job['id']}
        if method == 'job':
            return self.job_status(checked_text(data.get('id'), 'the review ID', 40))
        if method == 'cancel_job':
            with self.app.lock:
                job = self.app.jobs.get(data.get('id'))
                if job and job['status'] in {'queued','running'}:
                    job['cancelled'].set()
            return {'ok':True}
        if method == 'open_report':
            job_id = checked_text(data.get('id'), 'the review ID', 40)
            path = self.saved.get(job_id)
            if path is None or not path.is_file():
                raise ValueError('The Word report is no longer available. Check the Downloads folder.')
            if os.name != 'nt':
                raise ValueError('Open the Word report from Downloads.')
            os.startfile(str(path))
            return {'ok':True}
        raise ValueError('Unknown command')

    def close(self):
        for job in self.app.jobs.values():
            job['cancelled'].set()
        self.app.connection['token'] = ''
        self.app.pool.shutdown(wait=True, cancel_futures=True)
        self.app.repo.db.close()


def allowed_origin(origin):
    manifest = json.loads((ROOT/'native_config.json').read_text(encoding='utf-8'))
    return origin == 'chrome-extension://' + manifest['extension_id'] + '/'


def main():
    # Chrome supplies the extension origin. A website cannot launch the helper.
    if len(sys.argv) < 2 or not allowed_origin(sys.argv[1]):
        return 1
    if os.name == 'nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    service = NativeService(data_directory())
    output_lock = threading.Lock()
    slots = threading.BoundedSemaphore(6)
    def respond(request):
        try:
            result = service.dispatch(request.get('method'), request.get('data', {}))
            response = {'id':request.get('id'),'ok':True,'result':result}
        except (ValueError, ProviderError) as exc:
            response = {'id':request.get('id'),'ok':False,'error':str(exc)[:900]}
        except Exception:
            response = {'id':request.get('id'),'ok':False,'error':'The check could not finish. Try again or ask your trainer for help.'}
        try:
            with output_lock:
                sys.stdout.buffer.write(encode_message(response))
                sys.stdout.buffer.flush()
        except (OSError, ValueError):
            pass
        finally:
            slots.release()
    pool = ThreadPoolExecutor(max_workers=3)
    try:
        while True:
            request = read_message(sys.stdin.buffer)
            if request is None:
                break
            slots.acquire()
            pool.submit(respond, request)
    except (EOFError, ValueError, OSError):
        pass
    finally:
        pool.shutdown(wait=True, cancel_futures=False)
        service.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
