"""Bounded public TESS light-curve retrieval and transit-candidate screening."""

from __future__ import annotations

import hashlib
import io
import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import numpy as np
from astropy.io import fits
from astropy.timeseries import BoxLeastSquares

MAX_PRODUCTS = 5
MAX_PRODUCT_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_LIGHTCURVE_POINTS = 100_000
MAX_ANALYSIS_POINTS = 20_000
MAX_PERIODS = 8_000
MIN_PERIOD_DAYS = 0.5
MAX_PERIOD_DAYS = 20.0
TESS_DOWNLOAD_URL = "https://mast.stsci.edu/api/v0.1/Download/file"


class TessAnalysisError(ValueError):
    """Raised when the requested target or archive data cannot be analyzed."""


@dataclass(frozen=True)
class LightCurveProduct:
    sector: int
    provenance_name: str
    data_uri: str
    filename: str
    size_bytes: int


def validate_tic_id(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[0-9]{1,12}", value) or int(value) < 1:
        raise TessAnalysisError("Enter a numeric TIC identifier (up to 12 digits).")
    return str(int(value))


class MastArchive:
    """Small adapter around MAST metadata queries and bounded product downloads."""

    def list_light_curves(self, tic_id: str, sectors: list[int] | None) -> list[LightCurveProduct]:
        from astroquery.mast import Observations

        observations = Observations.query_criteria(
            obs_collection="TESS",
            target_name=tic_id,
            dataproduct_type="timeseries",
            dataRights="PUBLIC",
        )
        if not len(observations):
            return []

        products = Observations.get_product_list(observations)
        selected = Observations.filter_products(
            products,
            productSubGroupDescription="LC",
            productType="SCIENCE",
        )
        sectors_by_obs = {}
        provenance_by_obs = {}
        for row in observations:
            try:
                returned_tic = _observation_tic_id(row["target_name"])
                obs_id, sector = int(row["obsid"]), int(row["sequence_number"])
            except (KeyError, TypeError, ValueError):
                continue
            if returned_tic != tic_id:
                continue
            provenance_by_obs[obs_id] = str(row["provenance_name"]).strip().upper()
            if sector > 0:
                sectors_by_obs[obs_id] = sector
        result: list[LightCurveProduct] = []
        seen: set[str] = set()
        wanted = set(sectors or [])
        for row in selected:
            try:
                obs_id = int(row["obsID"])
            except (TypeError, ValueError):
                continue
            sector = sectors_by_obs.get(obs_id)
            data_uri = str(row["dataURI"])
            filename = str(row["productFilename"])
            provenance_name = provenance_by_obs.get(obs_id, "")
            if sector is None or (wanted and sector not in wanted) or data_uri in seen:
                continue
            if not data_uri.startswith("mast:TESS/product/") or provenance_name != "SPOC":
                continue
            try:
                size_bytes = int(row["size"])
            except (TypeError, ValueError, KeyError):
                continue
            if not filename.lower().endswith(".fits") or not 0 < size_bytes <= MAX_PRODUCT_BYTES:
                continue
            seen.add(data_uri)
            result.append(LightCurveProduct(sector, provenance_name, data_uri, filename, size_bytes))
            if len(result) == MAX_PRODUCTS:
                break
        return result

    def download(self, product: LightCurveProduct) -> bytes:
        url = f"{TESS_DOWNLOAD_URL}?uri={quote(product.data_uri, safe='')}"
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                if response.status_code == 302:
                    redirect_url = _validate_mast_redirect(response.headers.get("location", ""))
                else:
                    return _read_download_response(response, product)
            with client.stream("GET", redirect_url) as response:
                return _read_download_response(response, product)


def _validate_mast_redirect(location: str) -> str:
    try:
        parsed = urlsplit(location)
        port = parsed.port
    except ValueError as exc:
        raise TessAnalysisError("MAST returned an invalid download redirect.") from exc
    if (parsed.scheme != "https" or parsed.hostname != "stpubdata.s3.us-east-1.amazonaws.com"
            or port not in (None, 443) or parsed.username or parsed.password
            or not parsed.path.startswith("/tess/public/") or parsed.fragment):
        raise TessAnalysisError("MAST returned a download redirect outside the TESS public archive.")
    return location


def _read_download_response(response: httpx.Response, product: LightCurveProduct) -> bytes:
    response.raise_for_status()
    declared_size = response.headers.get("content-length")
    if declared_size and int(declared_size) > MAX_PRODUCT_BYTES:
        raise TessAnalysisError("A MAST product exceeds the per-file download limit.")
    data = bytearray()
    for chunk in response.iter_bytes():
        data.extend(chunk)
        if len(data) > MAX_PRODUCT_BYTES:
            raise TessAnalysisError("A MAST product exceeded the per-file download limit.")
    if len(data) != product.size_bytes:
        raise TessAnalysisError("Downloaded product size does not match the MAST manifest.")
    return bytes(data)


def _observation_tic_id(value: Any) -> str:
    match = re.fullmatch(r"(?:TIC\s*)?([0-9]{1,12})", str(value).strip(), re.IGNORECASE)
    if not match:
        raise ValueError("MAST observation has no valid TIC target identifier.")
    return str(int(match.group(1)))


def _read_lightcurve(data: bytes, expected_tic_id: str | None = None) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if not data or len(data) > MAX_PRODUCT_BYTES:
        raise TessAnalysisError("Light-curve file is empty or exceeds the file-size limit.")
    try:
        with fits.open(io.BytesIO(data), memmap=False, lazy_load_hdus=True) as hdul:
            if len(hdul) < 2 or hdul[1].data is None:
                raise TessAnalysisError("FITS file has no light-curve table extension.")
            table = hdul[1].data
            names = {name.upper(): name for name in table.names or []}
            if "TIME" not in names or "QUALITY" not in names:
                raise TessAnalysisError("FITS light curve must contain TIME and QUALITY columns.")
            flux_name = "PDCSAP_FLUX" if "PDCSAP_FLUX" in names else "SAP_FLUX"
            if flux_name not in names:
                raise TessAnalysisError("FITS light curve contains neither PDCSAP_FLUX nor SAP_FLUX.")
            time = np.asarray(table[names["TIME"]], dtype=float)
            flux = np.asarray(table[names[flux_name]], dtype=float)
            quality = np.asarray(table[names["QUALITY"]], dtype=np.int64)
            fits_metadata = {}
            for header in (hdul[0].header, hdul[1].header):
                for key in ("TELESCOP", "MISSION", "SECTOR", "CAMERA", "CCD", "CREATOR",
                            "PROCVER", "DATA_REL", "TIMESYS", "TSTART", "TSTOP"):
                    value = header.get(key)
                    if isinstance(value, str | int | float | bool) and not (
                            isinstance(value, float) and not math.isfinite(value)):
                        fits_metadata[key.lower()] = value.strip() if isinstance(value, str) else value
            if expected_tic_id is not None:
                fits_tic_id = next((header.get("TICID") for header in (hdul[0].header, hdul[1].header)
                                    if header.get("TICID") is not None), None)
                if fits_tic_id is None or _observation_tic_id(fits_tic_id) != expected_tic_id:
                    raise TessAnalysisError("Downloaded FITS target identifier does not match the requested TIC.")
    except TessAnalysisError:
        raise
    except Exception as exc:
        raise TessAnalysisError("Could not parse the TESS FITS light curve.") from exc

    if len(time) > MAX_LIGHTCURVE_POINTS:
        raise TessAnalysisError("Light curve exceeds the sample-count limit.")
    good = np.isfinite(time) & np.isfinite(flux) & (flux > 0) & (quality == 0)
    time, flux = time[good], flux[good]
    if len(time) < 30:
        raise TessAnalysisError("Fewer than 30 finite, quality-flagged-free samples remain.")
    order = np.argsort(time)
    time, flux = time[order], flux[order]
    unique = np.concatenate(([True], np.diff(time) > 0))
    time, flux = time[unique], flux[unique]
    median = float(np.median(flux))
    if not math.isfinite(median) or median <= 0:
        raise TessAnalysisError("Light curve has no positive finite median flux.")
    return time, flux / median, {
        "flux_column": flux_name,
        "quality_rule": "QUALITY == 0",
        "fits_metadata": fits_metadata,
    }


def _thin(time: np.ndarray, flux: np.ndarray, limit: int) -> tuple[np.ndarray, np.ndarray]:
    if len(time) <= limit:
        return time, flux
    edges = np.linspace(0, len(time), limit + 1, dtype=int)
    sampled_time = np.empty(limit)
    sampled_flux = np.empty(limit)
    for index, (start, stop) in enumerate(zip(edges[:-1], edges[1:], strict=False)):
        sampled_time[index] = np.mean(time[start:stop])
        sampled_flux[index] = np.median(flux[start:stop])
    return sampled_time, sampled_flux


def analyze_tic(tic: str, sectors: list[int] | None = None, archive: Any | None = None) -> dict[str, Any]:
    tic_id = validate_tic_id(tic)
    if sectors is not None and (not sectors or len(sectors) > MAX_PRODUCTS or
                                any(not isinstance(s, int) or not 1 <= s <= 999 for s in sectors) or
                                len(set(sectors)) != len(sectors)):
        raise TessAnalysisError(f"Choose between 1 and {MAX_PRODUCTS} distinct sector numbers.")
    archive = archive or MastArchive()
    products = archive.list_light_curves(tic_id, sectors)
    if not products:
        raise TessAnalysisError("MAST returned no matching public light-curve products.")
    if len(products) > MAX_PRODUCTS:
        raise TessAnalysisError("MAST returned more products than the configured analysis limit.")

    total_bytes = 0
    all_times: list[np.ndarray] = []
    all_fluxes: list[np.ndarray] = []
    product_records = []
    flux_columns: set[str] = set()
    for product in products:
        if not 0 < product.size_bytes <= MAX_PRODUCT_BYTES:
            raise TessAnalysisError("MAST product size is outside the configured limit.")
        total_bytes += product.size_bytes
        if total_bytes > MAX_TOTAL_BYTES:
            raise TessAnalysisError("Selected MAST products exceed the total download limit.")
        data = archive.download(product)
        time, flux, quality_info = _read_lightcurve(data, tic_id)
        all_times.append(time)
        all_fluxes.append(flux)
        flux_columns.add(quality_info["flux_column"])
        product_records.append({
            "sector": product.sector,
            "provenance_name": product.provenance_name,
            "filename": product.filename,
            "data_uri": product.data_uri,
            "sha256": hashlib.sha256(data).hexdigest(),
            "downloaded_bytes": len(data),
            **quality_info,
        })

    time = np.concatenate(all_times)
    flux = np.concatenate(all_fluxes)
    order = np.argsort(time)
    time, flux = time[order], flux[order]
    source_point_count = len(time)
    time, flux = _thin(time, flux, MAX_ANALYSIS_POINTS)
    baseline = float(time[-1] - time[0])
    maximum_period = min(MAX_PERIOD_DAYS, baseline / 3.0)
    if maximum_period <= MIN_PERIOD_DAYS:
        raise TessAnalysisError("The available baseline is too short to search the configured period range.")

    durations = np.array([0.04, 0.06, 0.08, 0.12, 0.18])
    model = BoxLeastSquares(time, flux)
    period_grid = model.autoperiod(
        durations,
        minimum_period=MIN_PERIOD_DAYS,
        maximum_period=maximum_period,
        minimum_n_transit=3,
        frequency_factor=2.0,
    )
    if len(period_grid) > MAX_PERIODS:
        indices = np.linspace(0, len(period_grid) - 1, MAX_PERIODS, dtype=int)
        period_grid = period_grid[indices]
    result = model.power(period_grid, durations, method="fast", oversample=5)
    powers = np.asarray(result.power, dtype=float)
    if not np.isfinite(powers).any():
        raise TessAnalysisError("BLS did not return any finite periodogram values.")
    best = int(np.nanargmax(powers))
    period_days = float(result.period[best])
    duration_days = float(result.duration[best])
    transit_time = float(result.transit_time[best])
    stats = model.compute_stats(period_days, duration_days, transit_time)
    depth = float(stats["depth"][0])
    noise_floor = float(np.std(flux - np.median(flux)))

    plot_time, plot_flux = _thin(time, flux, 1200)
    phase = ((plot_time - transit_time + period_days / 2.0) % period_days) / period_days
    return {
        "target": {"tic_id": tic_id},
        "status": "unvalidated_candidate_signal",
        "interpretation": (
            "A periodic box-shaped signal is a screening candidate only. This analysis does not "
            "establish a planet, reject eclipsing binaries or instrumental effects, or validate a host."
        ),
        "analysis": {
            "method": "Astropy BoxLeastSquares",
            "flux_columns": sorted(flux_columns),
            "quality_rule": "QUALITY == 0",
            "period_range_days": [MIN_PERIOD_DAYS, maximum_period],
            "duration_grid_days": durations.tolist(),
            "period_grid_size": len(period_grid),
            "analysis_points": len(time),
            "source_points": source_point_count,
            "analysis_resampled": source_point_count > len(time),
            "baseline_days": baseline,
            "period_days": period_days,
            "epoch_btjd": transit_time,
            "duration_hours": duration_days * 24.0,
            "depth_fraction": depth,
            "bls_power": float(result.power[best]),
            "flux_scatter_fraction": noise_floor,
            "sectors": sorted({item["sector"] for item in product_records}),
        },
        "products": product_records,
        "lightcurve_preview": [
            {"time_btjd": float(t), "phase": float(p), "relative_flux": float(f)}
            for t, p, f in zip(plot_time, phase, plot_flux, strict=False)
        ],
    }
