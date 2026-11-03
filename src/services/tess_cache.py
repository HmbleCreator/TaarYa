"""
Persistent disk cache for TESS light curves fetched from MAST.

Stores cleaned, quality-filtered, normalized light curves (time, flux) as compact
NumPy archives (.npz) so that downstream pipelines and harnesses run 100% offline
after initial retrieval.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np

from src.services.tess_service import (
    MastArchive,
    TessAnalysisError,
    _read_lightcurve,
    validate_tic_id,
)

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "tess_cache"


class TessCache:
    """Manages local storage and retrieval of public TESS light curves."""

    def __init__(self, cache_dir: Optional[Path | str] = None, archive: Optional[MastArchive] = None):
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.archive = archive or MastArchive()

    def _cache_path(self, tic_id: str, sector: int) -> Path:
        return self.cache_dir / f"tic_{tic_id}_s{sector:04d}.npz"

    def _meta_path(self, tic_id: str, sector: int) -> Path:
        return self.cache_dir / f"tic_{tic_id}_s{sector:04d}.json"

    def is_cached(self, tic_id: str, sector: int) -> bool:
        """Check if a specific TIC sector is already cached locally."""
        return self._cache_path(tic_id, sector).exists()

    def get_light_curve(
        self, tic_id: str, sector: int, force_download: bool = False
    ) -> Tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        """
        Load a sector light curve. Reads from cache if present; otherwise downloads
        from MAST, parses, caches, and returns (time, flux, metadata).
        """
        tic_id = validate_tic_id(tic_id)
        cache_file = self._cache_path(tic_id, sector)
        meta_file = self._meta_path(tic_id, sector)

        if not force_download and cache_file.exists():
            try:
                with np.load(cache_file) as data:
                    time = data["time"]
                    flux = data["flux"]
                metadata = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
                logger.debug(f"Loaded TIC {tic_id} sector {sector} from cache ({len(time)} points)")
                return time, flux, metadata
            except Exception as e:
                logger.warning(f"Failed reading cache for TIC {tic_id} sector {sector} ({e}), re-downloading")

        # Not cached or corrupted -> download via MastArchive
        products = self.archive.list_light_curves(tic_id, [sector])
        if not products:
            raise TessAnalysisError(f"MAST returned no public SPOC light curves for TIC {tic_id} sector {sector}")

        product = products[0]
        fits_bytes = self.archive.download(product)
        time, flux, meta = _read_lightcurve(fits_bytes, expected_tic_id=tic_id)

        # Save to cache
        np.savez_compressed(cache_file, time=time, flux=flux)
        meta_file.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        logger.info(f"Cached TIC {tic_id} sector {sector} to {cache_file} ({len(time)} points)")

        return time, flux, meta

    def get_sectors(
        self,
        tic_id: str,
        sectors: Optional[List[int]] = None,
        max_sectors: int = 3,
        force_download: bool = False,
    ) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Fetch multiple sectors for a target. If `sectors` is omitted, discovers available
        sectors from MAST or cached files and takes up to `max_sectors`.
        Returns a list of (time, flux) arrays.
        """
        tic_id = validate_tic_id(tic_id)

        if sectors is None:
            # First check if we have cached sectors
            cached_sectors = sorted(
                int(p.stem.split("_s")[1])
                for p in self.cache_dir.glob(f"tic_{tic_id}_s*.npz")
            )
            if len(cached_sectors) >= max_sectors:
                sectors = cached_sectors[:max_sectors]
            else:
                # Query MAST to discover available sectors
                products = self.archive.list_light_curves(tic_id, None)
                if not products:
                    raise TessAnalysisError(f"No public TESS products found for TIC {tic_id}")
                available_sectors = sorted({p.sector for p in products})
                sectors = available_sectors[:max_sectors]

        out: List[Tuple[np.ndarray, np.ndarray]] = []
        for s in sectors:
            t, f, _ = self.get_light_curve(tic_id, s, force_download=force_download)
            out.append((t, f))
        return out

    def prefetch(self, tic_id: str, sectors: Optional[List[int]] = None, max_sectors: int = 3) -> List[int]:
        """Download and cache sectors for offline use."""
        result = self.get_sectors(tic_id, sectors=sectors, max_sectors=max_sectors)
        cached_sectors = [
            int(p.stem.split("_s")[1])
            for p in self.cache_dir.glob(f"tic_{validate_tic_id(tic_id)}_s*.npz")
        ]
        return cached_sectors


# Module-level default instance for convenience
default_tess_cache = TessCache()

