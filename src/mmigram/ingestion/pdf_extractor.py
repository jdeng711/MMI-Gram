"""
PDF Ingestion and Text Extraction Engine for StEER Reconnaissance Reports.

Uses maintained PDF parsing libraries (pypdf) to extract text layers,
metadata, and identify image-based/scanned PDFs requiring future OCR fallback.
"""

from __future__ import annotations
import os
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


@dataclass
class PDFContentResult:
    """Standardized result of PDF text extraction."""
    file_path: str
    file_name: str
    is_valid_pdf: bool
    page_count: int = 0
    extracted_text: str = ""
    extraction_status: str = "PENDING"  # 'SUCCESS', 'IMAGE_BASED_PDF_NO_TEXT', 'CORRUPTED_PDF', 'FILE_NOT_FOUND'
    has_extractable_text: bool = False
    sha256_hash: Optional[str] = None
    file_size_bytes: int = 0
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PDFExtractor:
    """Extracts text content and metadata from local PDF documents."""

    def __init__(self, min_text_threshold: int = 25):
        self.min_text_threshold = min_text_threshold

    def extract(self, file_path: Union[str, Path]) -> PDFContentResult:
        path = Path(file_path)
        file_name = path.name

        # 1. Check file existence
        if not path.exists() or not path.is_file():
            return PDFContentResult(
                file_path=str(path),
                file_name=file_name,
                is_valid_pdf=False,
                extraction_status="FILE_NOT_FOUND",
                error_message=f"File not found at '{file_path}'",
            )

        # 2. Check file size & SHA-256 hash
        try:
            raw_bytes = path.read_bytes()
            file_size = len(raw_bytes)
            sha256 = hashlib.sha256(raw_bytes).hexdigest()
        except Exception as e:
            return PDFContentResult(
                file_path=str(path),
                file_name=file_name,
                is_valid_pdf=False,
                extraction_status="READ_ERROR",
                error_message=f"Failed to read file: {e}",
            )

        if file_size == 0:
            return PDFContentResult(
                file_path=str(path),
                file_name=file_name,
                is_valid_pdf=False,
                file_size_bytes=0,
                extraction_status="EMPTY_FILE",
                error_message="PDF file is 0 bytes",
            )

        # 3. Check PDF header
        if not raw_bytes.startswith(b"%PDF-"):
            return PDFContentResult(
                file_path=str(path),
                file_name=file_name,
                is_valid_pdf=False,
                file_size_bytes=file_size,
                sha256_hash=sha256,
                extraction_status="CORRUPTED_PDF",
                error_message="Invalid PDF header (does not start with %PDF-)",
            )

        # 4. Extract text using pypdf
        if not PYPDF_AVAILABLE:
            return PDFContentResult(
                file_path=str(path),
                file_name=file_name,
                is_valid_pdf=True,
                file_size_bytes=file_size,
                sha256_hash=sha256,
                extraction_status="LIBRARY_MISSING",
                error_message="pypdf library is not installed in the current environment",
            )

        try:
            reader = pypdf.PdfReader(str(path))
            page_count = len(reader.pages)
            pages_text: List[str] = []

            for i, page in enumerate(reader.pages):
                try:
                    text = page.extract_text() or ""
                    pages_text.append(text.strip())
                except Exception:
                    pages_text.append("")

            combined_text = "\n\n".join(t for t in pages_text if t).strip()
            total_chars = len(combined_text)

            # Determine whether the PDF has an extractable text layer or is raster/image-only
            if total_chars < self.min_text_threshold:
                return PDFContentResult(
                    file_path=str(path),
                    file_name=file_name,
                    is_valid_pdf=True,
                    page_count=page_count,
                    extracted_text="",
                    extraction_status="IMAGE_BASED_PDF_NO_TEXT",
                    has_extractable_text=False,
                    file_size_bytes=file_size,
                    sha256_hash=sha256,
                    error_message=(
                        f"PDF contains {page_count} page(s) but no extractable text layer was detected. "
                        "The document is likely scanned or image-based. Retaining candidate status for future OCR/vision node."
                    ),
                )

            return PDFContentResult(
                file_path=str(path),
                file_name=file_name,
                is_valid_pdf=True,
                page_count=page_count,
                extracted_text=combined_text,
                extraction_status="SUCCESS",
                has_extractable_text=True,
                file_size_bytes=file_size,
                sha256_hash=sha256,
            )

        except Exception as e:
            return PDFContentResult(
                file_path=str(path),
                file_name=file_name,
                is_valid_pdf=False,
                file_size_bytes=file_size,
                sha256_hash=sha256,
                extraction_status="CORRUPTED_PDF",
                error_message=f"pypdf encountered a parsing error: {e}",
            )
