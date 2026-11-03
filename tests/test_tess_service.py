import io
from unittest.mock import patch

import numpy as np
import pytest
from astropy.io import fits

from src.services.tess_service import (
    MAX_PRODUCTS,
    LightCurveProduct,
    MastArchive,
    TessAnalysisError,
    _read_lightcurve,
    _validate_mast_redirect,
    analyze_tic,
    validate_tic_id,
)


def fits_bytes(time, flux, quality=None):
    quality = np.zeros(len(time), dtype=np.int32) if quality is None else quality
    columns = [
        fits.Column(name="TIME", format="D", array=np.asarray(time, dtype=float)),
        fits.Column(name="PDCSAP_FLUX", format="D", array=np.asarray(flux, dtype=float)),
        fits.Column(name="SAP_FLUX", format="D", array=np.asarray(flux, dtype=float)),
        fits.Column(name="QUALITY", format="J", array=quality),
    ]
    output = io.BytesIO()
    primary = fits.PrimaryHDU()
    primary.header["TIMESYS"] = "TDB"
    primary.header["SECTOR"] = 1
    primary.header["TICID"] = 123
    fits.HDUList([primary, fits.BinTableHDU.from_columns(columns)]).writeto(output)
    return output.getvalue()


class FakeArchive:
    def __init__(self, data, products=None):
        self.data = data
        self.products = products or [
            LightCurveProduct(sector=1, provenance_name="SPOC", data_uri="mast:TESS/product/example.fits",
                              filename="example_lc.fits", size_bytes=len(data))
        ]
        self.downloaded = []

    def list_light_curves(self, tic_id, sectors):
        return self.products

    def download(self, product):
        self.downloaded.append(product)
        return self.data


def test_mast_adapter_limits_products_to_public_spoc_lightcurves():
    observations = [
        {"obsid": 7, "sequence_number": 12, "provenance_name": "SPOC", "target_name": "TIC 123"},
        {"obsid": 8, "sequence_number": 12, "provenance_name": "QLP", "target_name": "123"},
        {"obsid": 9, "sequence_number": 12, "provenance_name": "SPOC", "target_name": "TIC 999"},
    ]
    products = [
        {"obsID": 7, "dataURI": "mast:TESS/product/spoc.fits", "productFilename": "spoc_lc.fits",
         "size": 100},
        {"obsID": 8, "dataURI": "mast:TESS/product/qlp.fits", "productFilename": "qlp_lc.fits",
         "size": 100},
        {"obsID": 9, "dataURI": "mast:TESS/product/wrong-target.fits",
         "productFilename": "wrong-target_lc.fits", "size": 100},
    ]
    with patch("astroquery.mast.Observations.query_criteria", return_value=observations) as query, \
            patch("astroquery.mast.Observations.get_product_list", return_value=products), \
            patch("astroquery.mast.Observations.filter_products", return_value=products) as filter_products:
        found = MastArchive().list_light_curves("123", [12])

    query.assert_called_once_with(obs_collection="TESS", target_name="123",
                                  dataproduct_type="timeseries", dataRights="PUBLIC")
    filter_products.assert_called_once_with(products, productSubGroupDescription="LC",
                                             productType="SCIENCE")
    assert [item.provenance_name for item in found] == ["SPOC"]
    assert [item.sector for item in found] == [12]


def test_mast_download_redirect_is_limited_to_public_tess_s3():
    url = "https://stpubdata.s3.us-east-1.amazonaws.com/tess/public/tid/s0027/file.fits"
    assert _validate_mast_redirect(url) == url
    for location in (
        "http://stpubdata.s3.us-east-1.amazonaws.com/tess/public/file.fits",
        "https://evil.example/tess/public/file.fits",
        "https://stpubdata.s3.us-east-1.amazonaws.com/other/file.fits",
        "https://user@stpubdata.s3.us-east-1.amazonaws.com/tess/public/file.fits",
    ):
        with pytest.raises(TessAnalysisError, match="redirect"):
            _validate_mast_redirect(location)


def test_tic_identifier_is_numeric_and_canonicalized():
    assert validate_tic_id("000123") == "123"
    for value in ("TIC 123", "0", "-5", "12/34", "1" * 13):
        with pytest.raises(TessAnalysisError):
            validate_tic_id(value)


def test_lightcurve_reader_applies_finite_positive_flux_and_quality_filter():
    time = np.arange(40, dtype=float)
    flux = np.ones(40)
    flux[3] = np.nan
    flux[4] = -1
    quality = np.zeros(40, dtype=np.int32)
    quality[5] = 1
    data = fits_bytes(time, flux, quality)

    clean_time, clean_flux, meta = _read_lightcurve(data)

    assert len(clean_time) == 37
    assert np.all(np.isfinite(clean_flux))
    assert meta == {
        "flux_column": "PDCSAP_FLUX",
        "quality_rule": "QUALITY == 0",
        "fits_metadata": {"timesys": "TDB", "sector": 1},
    }


def test_lightcurve_reader_rejects_fits_for_a_different_tic():
    data = fits_bytes(np.arange(40), np.ones(40))
    with pytest.raises(TessAnalysisError, match="target identifier"):
        _read_lightcurve(data, expected_tic_id="999")


def test_reader_rejects_short_and_malformed_lightcurves():
    with pytest.raises(TessAnalysisError, match="30"):
        _read_lightcurve(fits_bytes(np.arange(20), np.ones(20)))
    with pytest.raises(TessAnalysisError, match="parse"):
        _read_lightcurve(b"not a FITS file")


def test_analysis_returns_candidate_with_archive_provenance_and_period():
    rng = np.random.default_rng(7)
    time = np.linspace(0, 54, 2400)
    flux = np.ones_like(time)
    phase = (time % 3.2)
    flux[phase < 0.11] -= 0.025
    flux += rng.normal(0, 0.001, len(time))
    data = fits_bytes(time, flux)
    archive = FakeArchive(data)

    result = analyze_tic("000123", archive=archive)

    assert result["target"]["tic_id"] == "123"
    assert result["status"] == "unvalidated_candidate_signal"
    assert abs(result["analysis"]["period_days"] - 3.2) < 0.08
    assert result["analysis"]["sectors"] == [1]
    assert len(result["products"][0]["sha256"]) == 64
    assert result["products"][0]["fits_metadata"]["timesys"] == "TDB"
    assert 0 < len(result["lightcurve_preview"]) <= 1200
    assert archive.downloaded


def test_analysis_rejects_duplicate_sectors_before_archive_access():
    archive = FakeArchive(b"")
    with pytest.raises(TessAnalysisError, match="distinct sector"):
        analyze_tic("123", sectors=[4, 4], archive=archive)
    assert not archive.downloaded


def test_analysis_rejects_archive_product_count_over_limit():
    data = fits_bytes(np.arange(40), np.ones(40))
    products = [
        LightCurveProduct(i + 1, "SPOC", f"mast:TESS/product/{i}.fits", f"{i}_lc.fits", len(data))
        for i in range(MAX_PRODUCTS + 1)
    ]
    archive = FakeArchive(data, products)
    with pytest.raises(TessAnalysisError, match="more products"):
        analyze_tic("123", archive=archive)
    assert not archive.downloaded
