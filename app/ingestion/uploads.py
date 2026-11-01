"""Documents a team uploads itself (PDF, Markdown, text).

Each upload is saved as a Document JSON file in data/uploads. The ingestion pipeline includes these
files, so a full re-index keeps them.
"""
import io
import re
import time
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.ingestion.schema import Document, make_id
from app.ingestion.text import normalize_text

UPLOAD_DIR = Path("data/uploads")
MAX_BYTES = 5 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}
DOC_ID = re.compile(r"^uploaded-[0-9a-f]{12}$")


class UploadError(ValueError):
    """The file cannot be used. The message is safe to show to the user."""


def clean_filename(name: str) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    return re.sub(r"[^\w.\- ]", "_", base).strip()[:120] or "document"


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise UploadError("Upload a PDF, Markdown or text file.")
    if len(data) > MAX_BYTES:
        raise UploadError("That file is larger than the 5 MB limit.")
    if suffix == ".pdf":
        try:
            pages = PdfReader(io.BytesIO(data)).pages
            text = "\n\n".join(page.extract_text() or "" for page in pages)
        except (PyPdfError, ValueError, KeyError, TypeError) as e:
            raise UploadError("That PDF could not be read.") from e
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise UploadError("That file is not UTF-8 text.") from e
    text = normalize_text(text).strip()
    if len(text) < 30:
        raise UploadError("No readable text found. Scanned PDFs need OCR first.")
    return text


def make_document(filename: str, text: str, username: str, access: str) -> Document:
    """The id comes from the file name, so uploading the same name again replaces the old version."""
    return Document(
        id=make_id("uploaded", filename.lower()), source_type="uploaded", title=filename, text=text,
        source=f"uploads/{filename}",
        metadata={"filename": filename, "uploaded_by": username, "uploaded_at": time.time(), "access": access},
    )


def save(doc: Document, folder: Path = UPLOAD_DIR) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{doc.id}.json").write_text(doc.model_dump_json(), encoding="utf-8")


def load_all(folder: Path = UPLOAD_DIR) -> list[Document]:
    if not folder.exists():
        return []
    return [Document.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("uploaded-*.json"))]


def remove(doc_id: str, folder: Path = UPLOAD_DIR) -> bool:
    if not DOC_ID.match(doc_id):  # never build a path from an unchecked id
        return False
    path = folder / f"{doc_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True
