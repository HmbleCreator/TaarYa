"""Tests for persistent TESS light-curve cache."""

from pathlib import Path
import numpy as np
import pytest

from src.services.tess_cache import TessCache
from src.services.tess_service import LightCurveProduct


class MockMastArchive:
    def __init__(self, data_bytes: bytes):
        self.data_bytes = data_bytes
        self.download_count = 0

    def list_light_curves(self, tic_id: str, sectors: list[int] | None) -> list[LightCurveProduct]:
        return [LightCurveProduct(1, "SPOC", "mast:TESS/product/test.fits", "test.fits", len(self.data_bytes))]

    def download(self, product: LightCurveProduct) -> bytes:
        self.download_count += 1
        return self.data_bytes


def _make_dummy_fits_bytes(tic_id: int = 12345) -> bytes:
    from astropy.io import fits
    import io

    pri_hdr = fits.Header()
    pri_hdr["TICID"] = tic_id
    pri_hdr["TELESCOP"] = "TESS"
    pri_hdu = fits.PrimaryHDU(header=pri_hdr)

    times = np.linspace(100.0, 127.0, 500)
    fluxes = 1000.0 + np.random.normal(0, 1.0, 500)
    qualities = np.zeros(500, dtype=np.int32)

    col1 = fits.Column(name="TIME", format="D", array=times)
    col2 = fits.Column(name="PDCSAP_FLUX", format="D", array=fluxes)
    col3 = fits.Column(name="QUALITY", format="J", array=qualities)
    tbl_hdu = fits.BinTableHDU.from_columns([col1, col2, col3])

    buf = io.BytesIO()
    hdul = fits.HDUList([pri_hdu, tbl_hdu])
    hdul.writeto(buf)
    return buf.getvalue()


def test_tess_cache_save_and_load(tmp_path: Path):
    fits_bytes = _make_dummy_fits_bytes(12345)
    mock_archive = MockMastArchive(fits_bytes)
    cache = TessCache(cache_dir=tmp_path, archive=mock_archive)

    assert not cache.is_cached("12345", 1)

    # First fetch: should call download
    t1, f1, meta1 = cache.get_light_curve("12345", 1)
    assert len(t1) == 500
    assert mock_archive.download_count == 1
    assert cache.is_cached("12345", 1)

    # Second fetch: should read from cache, no second download
    t2, f2, meta2 = cache.get_light_curve("12345", 1)
    assert mock_archive.download_count == 1  # count did not increase
    np.testing.assert_allclose(t1, t2)
    np.testing.assert_allclose(f1, f2)


def test_tess_cache_corrupt_recovery(tmp_path: Path):
    fits_bytes = _make_dummy_fits_bytes(12345)
    mock_archive = MockMastArchive(fits_bytes)
    cache = TessCache(cache_dir=tmp_path, archive=mock_archive)

    # Populate cache
    cache.get_light_curve("12345", 1)
    assert mock_archive.download_count == 1

    # Corrupt the cache file
    cache_file = cache._cache_path("12345", 1)
    cache_file.write_bytes(b"corrupt non-zip data")

    # Should detect corruption and re-download
    t, f, meta = cache.get_light_curve("12345", 1)
    assert mock_archive.download_count == 2
    assert len(t) == 500

