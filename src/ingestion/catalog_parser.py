"""Generic parser for multi-catalog astronomical tables."""

import logging
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CANONICAL_COLUMNS = [
    "source_id",
    "ra",
    "dec",
    "parallax",
    "parallax_error",
    "pmra",
    "pmdec",
    "phot_g_mean_mag",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "ruwe",
    "catalog_source",
    "object_class",
]


def _normalize_catalog_name(catalog_source: str) -> str:
    catalog = (catalog_source or "GAIA").strip().upper()
    return catalog.replace(" ", "-")


def _prefix_source_id(catalog_source: str, raw_source_id: Any) -> str:
    raw = str(raw_source_id).strip()
    if not raw:
        raw = "unknown"

    catalog = _normalize_catalog_name(catalog_source)
    if catalog == "GAIA":
        return raw
    if raw.upper().startswith(f"{catalog}:"):
        return raw
    return f"{catalog}:{raw}"


class CatalogParser:
    """Parse catalog CSV/JSON files into normalized star rows."""

    FIELD_MAPS: Dict[str, Dict[str, str]] = {
        "GAIA": {
            "source_id": "source_id",
            "sourceid": "source_id",
            "ra": "ra",
            "ra_deg": "ra",
            "dec": "dec",
            "dec_deg": "dec",
            "parallax": "parallax",
            "parallax_error": "parallax_error",
            "pmra": "pmra",
            "pmdec": "pmdec",
            "phot_g_mean_mag": "phot_g_mean_mag",
            "phot_bp_mean_mag": "phot_bp_mean_mag",
            "phot_rp_mean_mag": "phot_rp_mean_mag",
            "ruwe": "ruwe",
            "object_class": "object_class",
            "class": "object_class",
            "object_type": "object_class",
            "source_type": "object_class",
            "kind": "object_class",
        },
        "WISE": {
            "source_id": "source_id",
            "designation": "source_id",
            "objid": "source_id",
            "id": "source_id",
            "ra": "ra",
            "ra_deg": "ra",
            "dec": "dec",
            "dec_deg": "dec",
            "w1mag": "phot_g_mean_mag",
            "w1mpro": "phot_g_mean_mag",
            "w2mag": "phot_bp_mean_mag",
            "w3mag": "phot_rp_mean_mag",
        },
        "2MASS": {
            "source_id": "source_id",
            "designation": "source_id",
            "objid": "source_id",
            "id": "source_id",
            "ra": "ra",
            "ra_deg": "ra",
            "dec": "dec",
            "dec_deg": "dec",
            "jmag": "phot_g_mean_mag",
            "hmag": "phot_bp_mean_mag",
            "kmag": "phot_rp_mean_mag",
        },
        "PAN-STARRS": {
            "source_id": "source_id",
            "objid": "source_id",
            "obj_id": "source_id",
            "id": "source_id",
            "ra": "ra",
            "ra_deg": "ra",
            "dec": "dec",
            "dec_deg": "dec",
            "gmag": "phot_g_mean_mag",
            "g_mean_psf_mag": "phot_g_mean_mag",
            "rmag": "phot_bp_mean_mag",
            "r_mean_psf_mag": "phot_bp_mean_mag",
            "imag": "phot_rp_mean_mag",
            "i_mean_psf_mag": "phot_rp_mean_mag",
            "object_class": "object_class",
            "class": "object_class",
            "object_type": "object_class",
            "source_type": "object_class",
            "kind": "object_class",
        },
    }

    def __init__(
        self,
        catalog_source: str,
        chunk_size: int = 10000,
        field_map: Optional[Dict[str, str]] = None,
    ):
        self.catalog_source = _normalize_catalog_name(catalog_source)
        self.chunk_size = chunk_size
        self.field_map = {
            key.lower(): value
            for key, value in (field_map or {}).items()
        }
        self._catalog_field_map = dict(self.FIELD_MAPS.get(self.catalog_source, {}))

    def _build_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        df = frame.copy()
        df.columns = [str(col).strip().lower() for col in df.columns]
        df = df.rename(columns=self._catalog_field_map)
        if self.field_map:
            df = df.rename(columns=self.field_map)

        if "source_id" not in df.columns:
            for fallback in ("designation", "objid", "obj_id", "id", "source", "name"):
                if fallback in df.columns:
                    df["source_id"] = df[fallback]
                    break

        if "source_id" not in df.columns:
            df["source_id"] = [
                f"{self.catalog_source}:{index}"
                for index in range(len(df))
            ]

        if "ra" not in df.columns or "dec" not in df.columns:
            raise ValueError(f"{self.catalog_source} rows require ra/dec columns")

        if self.catalog_source != "GAIA":
            df["source_id"] = df["source_id"].apply(
                lambda value: _prefix_source_id(self.catalog_source, value)
            )
        else:
            df["source_id"] = df["source_id"].astype(str)

        df["catalog_source"] = self.catalog_source

        for column in CANONICAL_COLUMNS:
            if column not in df.columns:
                df[column] = None

        df = df[CANONICAL_COLUMNS]
        df = df.where(df.notna(), None)
        return df

    def parse_csv(self, filepath: Path) -> Iterator[pd.DataFrame]:
        logger.info(f"Parsing {self.catalog_source} CSV: {filepath}")
        for chunk in pd.read_csv(filepath, chunksize=self.chunk_size):
            yield self._build_frame(chunk)

    def parse_json(self, filepath: Path) -> Iterator[pd.DataFrame]:
        logger.info(f"Parsing {self.catalog_source} JSON: {filepath}")
        frame = pd.read_json(filepath)
        for start in range(0, len(frame), self.chunk_size):
            yield self._build_frame(frame.iloc[start:start + self.chunk_size])

    def parse_fits(self, filepath: Path) -> Iterator[pd.DataFrame]:
        logger.info(f"Parsing {self.catalog_source} FITS: {filepath}")
        try:
            from astropy.table import Table
        except Exception as exc:
            raise RuntimeError("FITS support requires astropy to be installed") from exc

        table = Table.read(filepath)
        frame = table.to_pandas()
        for start in range(0, len(frame), self.chunk_size):
            yield self._build_frame(frame.iloc[start:start + self.chunk_size])

    def parse(self, filepath: Path) -> Iterator[pd.DataFrame]:
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        suffix = filepath.suffix.lower()
        if suffix == ".csv":
            yield from self.parse_csv(filepath)
        elif suffix in {".fits", ".fit"}:
            yield from self.parse_fits(filepath)
        elif suffix in {".json", ".jsonl"}:
            yield from self.parse_json(filepath)
        else:
            raise ValueError(f"Unsupported format for {self.catalog_source}: {suffix}")
