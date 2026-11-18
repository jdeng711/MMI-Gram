"""
Recycled Media & Duplicate Detection Gate for MMI-Gram.

Computes cryptographic (SHA-256) and perceptual difference (dHash) hashes to detect
exact duplicate files and visually repeated photographs across the inbound queue.

Attribution:
  Adapted and expanded from Clara Yoon's RecycledMediaGate in QuakeLLMmap (quake_agent/gates/recycled_gate.py).
"""

from __future__ import annotations
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List, Union
from PIL import Image


@dataclass
class DuplicateCheckResult:
    """Result of duplicate and recycled media detection."""
    status: str = "UNIQUE"  # 'UNIQUE', 'EXACT_DUPLICATE', 'NEAR_DUPLICATE'
    is_unique: bool = True
    duplicate_of: Optional[str] = None
    sha256_hash: Optional[str] = None
    perceptual_hash: Optional[str] = None
    hamming_distance: Optional[int] = None
    reason: str = "Media is unique."

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_dhash(img: Image.Image) -> str:
    """Computes 64-bit difference hash (dHash) as 16-char hex string."""
    return RecycledMediaGate._compute_dhash(img)


def hamming_distance(h1: str, h2: str) -> int:
    """Computes bitwise Hamming distance between two 16-character hex hashes."""
    return RecycledMediaGate._hamming_distance(h1, h2)


class RecycledMediaGate:
    """
    Tracks and checks exact and near-duplicate files using cryptographic
    and perceptual image hashing.
    """

    def __init__(self, hamming_threshold: int = 4):
        self.hamming_threshold = hamming_threshold
        # Exact sha256 -> original filename
        self.seen_exact_hashes: Dict[str, str] = {}
        # List of (dhash_hex, filename)
        self.seen_perceptual_hashes: List[Tuple[str, str]] = []

    def reset(self):
        """Resets the duplicate registry for a new run."""
        self.seen_exact_hashes.clear()
        self.seen_perceptual_hashes.clear()

    def check(self, file_path: Union[str, Path]) -> DuplicateCheckResult:
        """
        Evaluates an input file for exact and near-duplicate matches.
        """
        p = Path(file_path).resolve()
        if not p.exists():
            return DuplicateCheckResult(
                status="UNIQUE",
                is_unique=True,
                reason="File does not exist on disk; duplicate check bypassed.",
            )

        file_name = p.name

        # 1. Exact Cryptographic Hash (SHA-256)
        raw_bytes = p.read_bytes()
        sha256_val = hashlib.sha256(raw_bytes).hexdigest()

        if sha256_val in self.seen_exact_hashes:
            orig = self.seen_exact_hashes[sha256_val]
            return DuplicateCheckResult(
                status="EXACT_DUPLICATE",
                is_unique=False,
                duplicate_of=orig,
                sha256_hash=sha256_val,
                reason=f"Exact duplicate detected (SHA-256 matches '{orig}').",
            )

        # Register exact hash
        self.seen_exact_hashes[sha256_val] = file_name

        # 2. Perceptual Image Hash (dHash)
        phash_val: Optional[str] = None
        near_match_file: Optional[str] = None
        min_distance: Optional[int] = None

        img = self._extract_primary_image(p)
        if img:
            phash_val = self._compute_dhash(img)
            # Compare against previously registered perceptual hashes
            for prev_hash, prev_file in self.seen_perceptual_hashes:
                dist = self._hamming_distance(phash_val, prev_hash)
                if dist <= self.hamming_threshold:
                    if min_distance is None or dist < min_distance:
                        min_distance = dist
                        near_match_file = prev_file

            # Register perceptual hash
            self.seen_perceptual_hashes.append((phash_val, file_name))

        if near_match_file is not None and min_distance is not None:
            return DuplicateCheckResult(
                status="NEAR_DUPLICATE",
                is_unique=False,
                duplicate_of=near_match_file,
                sha256_hash=sha256_val,
                perceptual_hash=phash_val,
                hamming_distance=min_distance,
                reason=(
                    f"Visually near-duplicate photograph detected (dHash distance {min_distance} "
                    f"<= {self.hamming_threshold} compared to '{near_match_file}')."
                ),
            )

        return DuplicateCheckResult(
            status="UNIQUE",
            is_unique=True,
            sha256_hash=sha256_val,
            perceptual_hash=phash_val,
            reason="Observation media is unique.",
        )

    def _extract_primary_image(self, path: Path) -> Optional[Image.Image]:
        ext = path.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"):
            try:
                return Image.open(path).copy()
            except Exception:
                return None
        elif ext == ".pdf":
            try:
                import pypdf
                import io
                reader = pypdf.PdfReader(str(path))
                for page in reader.pages:
                    if len(page.images) > 0:
                        first_img = page.images[0]
                        img_bytes = first_img.data
                        return Image.open(io.BytesIO(img_bytes)).copy()
            except Exception:
                pass
        return None

    @staticmethod
    def _compute_dhash(img: Image.Image) -> str:
        """
        Computes 64-bit difference hash (dHash).
        Resizes to 9x8 grayscale, evaluates row-wise adjacent intensity gradients.
        """
        resized = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(resized.getdata())
        diff = []
        for row in range(8):
            for col in range(8):
                left = pixels[row * 9 + col]
                right = pixels[row * 9 + col + 1]
                diff.append(1 if left > right else 0)
        decimal_val = 0
        for bit in diff:
            decimal_val = (decimal_val << 1) | bit
        return f"{decimal_val:016x}"

    @staticmethod
    def _hamming_distance(h1: str, h2: str) -> int:
        """Computes bitwise Hamming distance between two 16-character hex hashes."""
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
