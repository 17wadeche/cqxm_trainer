"""Install user-selected baseline PDFs once; local replacement revisions win."""
import hashlib
import json
from pathlib import Path

from config import PROCEDURES, MAX_FILE_BYTES
from models import EvidenceSource, extracted_digest


def _asset(directory, filename):
    if not isinstance(filename,str) or not filename or Path(filename).name != filename or '\\' in filename:
        raise ValueError('Invalid bundled filename')
    path=directory/filename
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Bundled file is too large')
    return path.read_bytes()


def load_defaults(repo, directory):
    """Return setup errors without making startup, token entry or uploads fail."""
    pending=repo.defaults_pending()
    if not pending:
        return []
    directory=Path(directory)
    try:
        manifest=json.loads(_asset(directory,'manifest.json'))
        items=manifest['procedures']
        if manifest['schema_version']!=1 or not isinstance(items,list):
            raise ValueError('Invalid manifest')
        ids=[item['document_id'] for item in items]
        if len(ids)!=len(set(ids)) or set(ids)!={docid for docid,_ in PROCEDURES}:
            raise ValueError('Unexpected default procedure list')
    except (OSError,ValueError,TypeError,KeyError):
        return ['The bundled procedures are missing or damaged. Re-extract the complete app package, or upload the missing procedures in Training setup.']
    entries,errors=[],[]
    for item in items:
        docid=item['document_id']
        if docid not in pending:
            continue
        try:
            original=_asset(directory,item['pdf'])
            value=json.loads(_asset(directory,item['index']))
            source=EvidenceSource.model_validate(value['source'])
            warnings=value['warnings']
            if (not original.startswith(b'%PDF-') or hashlib.sha256(original).hexdigest()!=item['sha256']
                or source.file_sha256!=item['sha256'] or source.document_id!=docid
                or source.revision!=item['revision'] or source.name!=item['pdf']
                or source.kind!='procedure' or not source.approved_revision or source.record_id is not None
                or extracted_digest(source.chunks)!=source.extracted_text_sha256
                or not isinstance(warnings,list) or not all(isinstance(w,str) for w in warnings)):
                raise ValueError('Invalid bundled procedure')
            entries.append((source,warnings))
        except (OSError,ValueError,TypeError,KeyError):
            errors.append(f'Bundled procedure {docid} is missing or damaged. Re-extract the complete app package, or upload its replacement in Training setup.')
    repo.install_defaults(entries)
    return errors
