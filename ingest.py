import hashlib
import io
import re
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from config import MAX_FILE_BYTES
from models import Chunk, EvidenceSource, extracted_digest
def split_text(text, size=2400, overlap=180):
    text = text.replace("\x00", "").strip()
    while text:
        if len(text) <= size:
            yield text
            break
        stop = text.rfind("\n", size // 2, size)
        if stop < 0:
            stop = text.rfind(" ", size // 2, size)
        if stop < 0:
            stop = size
        yield text[:stop].strip()
        text = text[max(1, stop-overlap):].strip()
def _docx_blocks(parent, prefix="Body"):
    element = parent.element.body if hasattr(parent, "element") else parent._tc
    index = 0
    for child in element.iterchildren():
        index += 1
        if child.tag.endswith("}p"):
            p = Paragraph(child, parent)
            if p.text.strip():
                yield (f"{prefix}, paragraph {index}", p.text)
        elif child.tag.endswith("}tbl"):
            t = Table(child, parent)
            for rnum, row in enumerate(t.rows, 1):
                visited = set()
                for cnum, cell in enumerate(row.cells, 1):
                    if cell._tc in visited:
                        continue
                    visited.add(cell._tc)
                    yield from _docx_blocks(cell, f"{prefix}, table {index}, row {rnum}, cell {cnum}")
def extract(name, data, *, depth=0):
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("Choose a nonempty file smaller than 20 MB.")
    ext = Path(name).suffix.lower()
    blocks, warnings = [], []
    if ext == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("This file does not contain a PDF.")
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("Export an unencrypted copy before uploading this PDF.")
        if len(reader.pages) > 600:
            raise ValueError("This PDF exceeds the 600-page limit. Upload the relevant document separately.")
        for number, page in enumerate(reader.pages, 1):
            if page.get('/Contents') is None:
                text = ''
            else:
                try:
                    text = page.extract_text(extraction_mode="layout") or ""
                except (KeyError, ValueError):
                    text = page.extract_text() or ''
                    warnings.append(f"{name}: page {number} used fallback text extraction; inspect its layout manually.")
            if len(text.strip()) < 30:
                warnings.append(f"{name}: page {number} has little or no readable text; scanned content needs OCR or manual review.")
            if text.strip():
                blocks.append((f"PDF page {number}", text))
        fields = reader.get_fields() or {}
        for field_name, info in fields.items():
            blocks.append((f"PDF form field {field_name}", f"{field_name}: {info.get('/V', '[no value]')}"))
        warnings.append(f"{name}: PDF text extraction does not establish the meaning of diagrams or flattened checkbox marks. Inspect form and visual evidence when relevant.")
    elif ext == ".docx":
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if sum(e.file_size for e in entries) > 80 * 1024 * 1024:
                    raise ValueError("The expanded Word file is too large.")
                if "word/document.xml" not in archive.namelist():
                    raise ValueError("This is not a Word document.")
                if any(e.filename.startswith("word/media/") for e in entries):
                    warnings.append(f"{name}: embedded images are not interpreted; verify any diagram or screenshot that affects the review.")
            doc = Document(io.BytesIO(data))
            blocks.extend(_docx_blocks(doc))
            for number, section in enumerate(doc.sections, 1):
                for label, component in [("header", section.header), ("footer", section.footer)]:
                    for p in component.paragraphs:
                        if p.text.strip():
                            blocks.append((f"Section {number} {label}", p.text))
        except BadZipFile as exc:
            raise ValueError("This file does not contain a valid DOCX.") from exc
    elif ext == ".txt":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Save text files as UTF-8 before uploading.") from exc
        for i, paragraph in enumerate(re.split(r"\n\s*\n", text), 1):
            if paragraph.strip():
                blocks.append((f"Text paragraph {i}", paragraph))
    else:
        from attachment_text import extra_blocks
        try:
            blocks, warnings = extra_blocks(name, data, depth)
        except ValueError:
            raise
        except Exception:
            raise ValueError('This attachment could not be read. Export a text-based copy.') from None
    if sum(len(text) for _, text in blocks) > 5_000_000:
        raise ValueError('The extracted text exceeds the 5 MB limit. Split this attachment.')
    chunks = []
    for locator, text in blocks:
        for i, part in enumerate(split_text(text), 1):
            chunks.append(Chunk(id=f"c{len(chunks)+1:05d}", locator=f"{locator}, part {i}", text=part))
    if not chunks or sum(len(c.text) for c in chunks) < 40:
        raise ValueError("No usable text was found. Upload a text-based export or an OCR-processed copy.")
    if len(chunks) > 5000:
        raise ValueError("Too many text sections. Split this source into individual documents.")
    return chunks, warnings
def verify_record(chunks, record_id, kind):
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,40}", record_id):
        raise ValueError("Enter a valid GCH record ID.")
    full = "\n".join(c.text for c in chunks)
    escaped = re.escape(record_id)
    if not re.search(r"(?<![A-Za-z0-9])" + escaped + r"(?![A-Za-z0-9])", full):
        raise ValueError(f"The {kind} does not contain record ID {record_id}. Choose the matching export.")
    value_pattern=r'\d{6,12}(?:-\d{1,4})?' if record_id.isdigit() else r'[A-Za-z0-9_-]{3,40}'
    labeled = re.findall(r"\b(?:product\s+event(?:\s+(?:transaction\s+id|id|number|no\.?))?|event\s+id|PE\s*(?:id|number)?)\s*[:#=]+\s*("+value_pattern+r")", full, re.I)
    labeled += re.findall(r"\b(?:event\s+id|product\s+event\s+transaction\s+id)\s+(\d{6,12})\b",full,re.I)
    def matches(value):
        return value==record_id or (record_id.isdigit() and bool(re.fullmatch(r'0*'+re.escape(record_id)+r'(?:-\d{1,4})?',value)))
    if labeled and any(not matches(value) for value in labeled):
        raise ValueError("The report contains a different labeled event ID. Verify the selected GCH record and export.")
    if kind == "PESR" and not re.search(r"product\s+event\s+summary(?:\s+report)?", full, re.I):
        raise ValueError("The file is not identifiable as a Product Event Summary Report.")
    if kind == 'DER' and not re.search(r'\bdetailed\s+event\s+report\b',full[:2500],re.I):
        raise ValueError('The file is not identifiable as a Detailed Event Report.')
def source_from_bytes(name, data, source_id, kind, document_id, record_id=None,
                      revision=None, approved=False):
    chunks, warnings = extract(name, data)
    if kind == "record":
        if document_id=='PRIMARY':
            start='\n'.join(c.text for c in chunks)[:2500]
            if re.search(r'\bdetailed\s+event\s+report\b',start,re.I):document_id='DER'
            elif re.search(r'product\s+event\s+summary(?:\s+report)?',start,re.I):document_id='PESR'
            else:raise ValueError('Choose a Detailed Event Report or Product Event Summary Report for this event.')
        if document_id=='DER':
            compact=[]
            for c in chunks:
                lines=[re.sub(r'[ \t]+',' ',line).strip() for line in c.text.splitlines()]
                text='\n'.join(line for line in lines if line and line not in {'Global Complaint Handling','Medtronic Confidential'})
                if text:compact.append(c.model_copy(update={'text':text}))
            chunks=compact
        if document_id == 'ATTACHMENT':
            if not record_id or not re.fullmatch(r'[A-Za-z0-9_-]{3,40}', record_id):
                raise ValueError('An incoming attachment needs its selected GCH event ID.')
            labels = re.findall(r'\b(?:event\s+id|product\s+event(?:\s+id)?)\s*[:#=]\s*([A-Za-z0-9_-]+)', '\n'.join(c.text for c in chunks), re.I)
            if any(value != record_id and not (record_id.isdigit() and value.isdigit() and int(value) == int(record_id)) for value in labels):
                raise ValueError('This attachment labels a different event ID. Confirm the correct attachment with your trainer.')
        else:
            verify_record(chunks, record_id, document_id)
    return EvidenceSource(id=source_id, kind=kind, name=Path(name).name,
        document_id=document_id, record_id=record_id, revision=revision,
        approved_revision=approved, file_sha256=hashlib.sha256(data).hexdigest(),
        extracted_text_sha256=extracted_digest(chunks), chunks=chunks), warnings
