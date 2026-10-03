"""
Resume upload → plain text.

Accepts PDF, DOCX and TXT up to APPLY_RESUME_MAX_BYTES. Files are identified
by their content (magic bytes), not by the name the browser sent, and only
the extracted text is kept — the uploaded file itself is never stored.

PDF and DOCX parsing runs in a separate, resource-limited process
(resume_worker.py) under a hard deadline: a decompression bomb can only exhaust
that worker, which is killed, never the web server. DOCX archives are also
screened for absurd expansion before they are handed to the worker.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path

from app.core.config import settings

MAX_CHARS = 40_000
PARSE_TIMEOUT_SECONDS = 25
_WORKER = Path(__file__).resolve().with_name("resume_worker.py")
_ZIP_MAX_TOTAL = 40 * 1024 * 1024    # uncompressed bytes across all entries
_ZIP_MAX_RATIO = 150                 # uncompressed / compressed, for entries over 1 MB


class ResumeFileError(Exception):
    """User-safe reason a file could not be read."""


def _check_docx_zip(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile:
        raise ResumeFileError("That file looks damaged. Try saving it again as PDF or DOCX.") from None
    if not any(i.filename == "word/document.xml" for i in infos):
        raise ResumeFileError("Only PDF, DOCX or plain-text resumes are supported.")
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > 1_000_000 and info.file_size > _ZIP_MAX_RATIO * max(info.compress_size, 1):
            raise ResumeFileError("That DOCX file expands to an unreasonable size and was not opened.")
    if total > _ZIP_MAX_TOTAL or len(infos) > 2000:
        raise ResumeFileError("That DOCX file expands to an unreasonable size and was not opened.")


def detect_kind(data: bytes, filename: str) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        _check_docx_zip(data)
        return "docx"
    if filename.lower().endswith((".txt", ".md")):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ResumeFileError("That text file is not UTF-8 encoded.") from None
        return "txt"
    raise ResumeFileError("Only PDF, DOCX or plain-text resumes are supported.")


async def _parse_in_worker(kind: str, data: bytes) -> str:
    # Run the worker as a plain script in isolated mode (-I): it imports only
    # the parsers, never the app's settings or database layer.
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", str(_WORKER), kind,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(data), PARSE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ResumeFileError("Reading that file took too long. Paste your resume text instead.") from None
    try:
        result = json.loads(out.decode("utf-8") or "{}")
    except ValueError:
        result = {}
    if not result.get("ok"):
        error = result.get("error")
        if error == "encrypted":
            raise ResumeFileError("That PDF is password-protected. Remove the password and upload it again.")
        if error == "too_large" or proc.returncode not in (0, None):
            raise ResumeFileError("That file is too complex to read safely. Paste your resume text instead.")
        raise ResumeFileError(
            "That PDF could not be read. Try exporting it again." if kind == "pdf" else "That DOCX file could not be read."
        )
    return str(result.get("text", ""))


def _clean(text: str) -> str:
    text = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    return text.replace("\x00", "").strip()


async def extract_resume_text(data: bytes, filename: str) -> str:
    if not data:
        raise ResumeFileError("The file is empty.")
    if len(data) > settings.APPLY_RESUME_MAX_BYTES:
        raise ResumeFileError("The file is too large (max 5 MB).")
    kind = detect_kind(data, filename or "")
    text = data.decode("utf-8") if kind == "txt" else await _parse_in_worker(kind, data)
    text = _clean(text)
    if len(text) < 50:
        raise ResumeFileError(
            "No readable text was found in that file (scanned image PDFs are not supported). "
            "Paste your resume text instead."
        )
    return text[:MAX_CHARS]
