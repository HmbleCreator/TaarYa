"""Scientific output utilities for TaarYa.

Provides standard astronomy data formats for interoperability with
TOPCAT, Aladin, DS9, and other VO-compliant tools.
"""

import csv
import io
import json
import logging
import math
import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

VOTABLE_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<VOTABLE version="1.4" xmlns="http://www.ivoa.net/xml/VOTable/v1.3"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://www.ivoa.net/xml/VOTable/v1.3 http://www.ivoa.net/xml/VOTable/VOTable-1.3.xsd">
  <RESOURCE name="TaarYa_Results" type="results">
    <COOSYS ID="ICRS" system="ICRS" epoch="J2016.0"/>
    <TABLE name="stars">
      <DESCRIPTION>Stars retrieved from TaarYa hybrid search with discovery scoring</DESCRIPTION>
      <FIELD ID="source_id" name="source_id" ucd="meta.id;meta.main" datatype="char" arraysize="*">
        <DESCRIPTION>Gaia DR3 Source ID</DESCRIPTION>
      </FIELD>
      <FIELD ID="ra" name="ra" ucd="pos.eq.ra;meta.main" ref="ICRS" datatype="double" unit="deg" precision="7">
        <DESCRIPTION>Right Ascension (ICRS)</DESCRIPTION>
      </FIELD>
      <FIELD ID="dec" name="dec" ucd="pos.eq.dec;meta.main" ref="ICRS" datatype="double" unit="deg" precision="7">
        <DESCRIPTION>Declination (ICRS)</DESCRIPTION>
      </FIELD>
      <FIELD ID="parallax" name="parallax" ucd="pos.parallax" datatype="double" unit="mas" precision="4">
        <DESCRIPTION>Parallax</DESCRIPTION>
      </FIELD>
      <FIELD ID="parallax_error" name="parallax_error" ucd="stat.error;pos.parallax" datatype="double" unit="mas" precision="4">
        <DESCRIPTION>Parallax uncertainty</DESCRIPTION>
      </FIELD>
      <FIELD ID="pmra" name="pmra" ucd="pos.pm;pos.eq.ra" datatype="double" unit="mas/yr" precision="4">
        <DESCRIPTION>Proper motion in RA</DESCRIPTION>
      </FIELD>
      <FIELD ID="pmra_error" name="pmra_error" ucd="stat.error;pos.pm;pos.eq.ra" datatype="double" unit="mas/yr" precision="4">
        <DESCRIPTION>Proper motion in RA uncertainty</DESCRIPTION>
      </FIELD>
      <FIELD ID="pmdec" name="pmdec" ucd="pos.pm;pos.eq.dec" datatype="double" unit="mas/yr" precision="4">
        <DESCRIPTION>Proper motion in Dec</DESCRIPTION>
      </FIELD>
      <FIELD ID="pmdec_error" name="pmdec_error" ucd="stat.error;pos.pm;pos.eq.dec" datatype="double" unit="mas/yr" precision="4">
        <DESCRIPTION>Proper motion in Dec uncertainty</DESCRIPTION>
      </FIELD>
      <FIELD ID="radial_velocity" name="radial_velocity" ucd="spect.dopplerVeloc.opt;stat.mean" datatype="double" unit="km/s" precision="2">
        <DESCRIPTION>Radial velocity</DESCRIPTION>
      </FIELD>
      <FIELD ID="radial_velocity_error" name="radial_velocity_error" ucd="stat.error;spect.dopplerVeloc.opt;stat.mean" datatype="double" unit="km/s" precision="2">
        <DESCRIPTION>Radial velocity uncertainty</DESCRIPTION>
      </FIELD>
      <FIELD ID="phot_g_mean_mag" name="phot_g_mean_mag" ucd="phot.mag;em.opt.gaia.g" datatype="double" unit="mag" precision="3">
        <DESCRIPTION>Gaia G-band mean magnitude</DESCRIPTION>
      </FIELD>
      <FIELD ID="phot_bp_mean_mag" name="phot_bp_mean_mag" ucd="phot.mag;em.opt.gaia.bp" datatype="double" unit="mag" precision="3">
        <DESCRIPTION>Gaia BP-band mean magnitude</DESCRIPTION>
      </FIELD>
      <FIELD ID="phot_rp_mean_mag" name="phot_rp_mean_mag" ucd="phot.mag;em.opt.gaia.rp" datatype="double" unit="mag" precision="3">
        <DESCRIPTION>Gaia RP-band mean magnitude</DESCRIPTION>
      </FIELD>
      <FIELD ID="bp_rp" name="bp_rp" ucd="phot.color;em.opt.gaia.bp;em.opt.gaia.rp" datatype="double" unit="mag" precision="3">
        <DESCRIPTION>BP - RP color index</DESCRIPTION>
      </FIELD>
      <FIELD ID="ruwe" name="ruwe" ucd="stat.fit.goodness" datatype="double" precision="3">
        <DESCRIPTION>Renormalized Unit Weight Error (astrometric quality)</DESCRIPTION>
      </FIELD>
      <FIELD ID="discovery_score" name="discovery_score" ucd="meta.code.qual" datatype="float" precision="2">
        <DESCRIPTION>Anomaly score (higher = more interesting)</DESCRIPTION>
      </FIELD>
      <FIELD ID="discovery_reasons" name="discovery_reasons" ucd="meta.note" datatype="char" arraysize="*">
        <DESCRIPTION>Reasons for discovery score</DESCRIPTION>
      </FIELD>
      <PARAM name="TaarYa_Version" datatype="char" arraysize="*" value="1.0.0"/>
      <PARAM name="Query_Time" ucd="time.epoch" datatype="char" arraysize="*" value="{query_time}"/>
      <PARAM name="Provenance_Type" datatype="char" arraysize="*" value="{provenance_type}"/>
      <PARAM name="Provenance_Query" datatype="char" arraysize="*" value="{provenance_query}"/>
      <DATA>
        <TABLEDATA>
{table_data}        </TABLEDATA>
      </DATA>
    </TABLE>
    <INFO name="QueryTime" value="{query_time}"/>
    <INFO name="TotalStars" value="{total_stars}"/>
    <INFO name="Provenance_Type" value="{provenance_type}"/>
    <INFO name="Provenance_RawQuery" value="{provenance_query}"/>
    <INFO name="System" value="TaarYa"/>
  </RESOURCE>
</VOTABLE>"""

ROW_TEMPLATE = """          <TR>
            <TD>{source_id}</TD>
            <TD>{ra}</TD>
            <TD>{dec}</TD>
            <TD>{parallax}</TD>
            <TD>{parallax_error}</TD>
            <TD>{pmra}</TD>
            <TD>{pmra_error}</TD>
            <TD>{pmdec}</TD>
            <TD>{pmdec_error}</TD>
            <TD>{rv}</TD>
            <TD>{rv_error}</TD>
            <TD>{phot_g}</TD>
            <TD>{phot_bp}</TD>
            <TD>{phot_rp}</TD>
            <TD>{bp_rp}</TD>
            <TD>{ruwe}</TD>
            <TD>{discovery_score}</TD>
            <TD>{discovery_reasons}</TD>
          </TR>"""

def _sanitize_value(val: Any) -> str:
    """Convert value to safe string for VOTable."""
    if val is None:
        return ""
    if isinstance(val, float):
        if not math.isfinite(val):
            return ""
        return f"{val:.7g}"
    return str(val)

def _format_row(star: Dict) -> str:
    """Format a single star as VOTable TR element."""
    bp_rp = None
    if star.get("phot_bp_mean_mag") is not None and star.get("phot_rp_mean_mag") is not None:
        bp_rp = star["phot_bp_mean_mag"] - star["phot_rp_mean_mag"]

    reasons = star.get("discovery_reasons", [])
    if isinstance(reasons, list):
        reasons = "; ".join(reasons)
    elif reasons is None:
        reasons = ""

    return ROW_TEMPLATE.format(
        source_id=_sanitize_value(star.get("source_id")),
        ra=_sanitize_value(star.get("ra")),
        dec=_sanitize_value(star.get("dec")),
        parallax=_sanitize_value(star.get("parallax")),
        parallax_error=_sanitize_value(star.get("parallax_error")),
        pmra=_sanitize_value(star.get("pmra")),
        pmra_error=_sanitize_value(star.get("pmra_error")),
        pmdec=_sanitize_value(star.get("pmdec")),
        pmdec_error=_sanitize_value(star.get("pmdec_error")),
        rv=_sanitize_value(star.get("radial_velocity")),
        rv_error=_sanitize_value(star.get("radial_velocity_error")),
        phot_g=_sanitize_value(star.get("phot_g_mean_mag")),
        phot_bp=_sanitize_value(star.get("phot_bp_mean_mag")),
        phot_rp=_sanitize_value(star.get("phot_rp_mean_mag")),
        bp_rp=_sanitize_value(bp_rp),
        ruwe=_sanitize_value(star.get("ruwe")),
        discovery_score=_sanitize_value(star.get("discovery_score")),
        discovery_reasons=reasons.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
    )



def export_to_votable(stars: List[Dict], query_time: Optional[str] = None) -> str:
    """Export stars to VOTable format (IVOA standard).

    Args:
        stars: List of star dictionaries
        query_time: Optional timestamp of query

    Returns:
        VOTable XML string
    """
    if query_time is None:
        query_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

    table_data = "\n".join(_format_row(s) for s in stars)
    
    # Extract provenance from first star if available
    prov_type = "N/A"
    prov_query = "N/A"
    if stars and "_provenance" in stars[0]:
        prov = stars[0]["_provenance"]
        prov_type = prov.get("query_type", "N/A")
        prov_query = prov.get("raw_query", "N/A").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return VOTABLE_TEMPLATE.format(
        table_data=table_data,
        query_time=query_time,
        total_stars=len(stars),
        provenance_type=prov_type,
        provenance_query=prov_query
    )


def export_to_csv(stars: List[Dict]) -> str:
    """Export stars to CSV format.

    Args:
        stars: List of star dictionaries

    Returns:
        CSV string
    """
    if not stars:
        return ""

    fieldnames = [
        "source_id", "ra", "dec", "parallax", "parallax_error",
        "pmra", "pmra_error", "pmdec", "pmdec_error", 
        "radial_velocity", "radial_velocity_error",
        "phot_g_mean_mag", "phot_bp_mean_mag",
        "phot_rp_mean_mag", "bp_rp", "ruwe", "discovery_score",
        "discovery_reasons"
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for star in stars:
        row = star.copy()
        if star.get("phot_bp_mean_mag") is not None and star.get("phot_rp_mean_mag") is not None:
            row["bp_rp"] = star["phot_bp_mean_mag"] - star["phot_rp_mean_mag"]
        else:
            row["bp_rp"] = None

        reasons = star.get("discovery_reasons", [])
        if isinstance(reasons, list):
            row["discovery_reasons"] = "; ".join(reasons)
        elif reasons is None:
            row["discovery_reasons"] = ""

        writer.writerow(row)

    return output.getvalue()


def export_to_json(stars: List[Dict], include_metadata: bool = True) -> str:
    """Export stars to JSON format.

    Args:
        stars: List of star dictionaries
        include_metadata: Include query metadata

    Returns:
        JSON string
    """
    data = {
        "source": "TaarYa",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_results": len(stars),
        "stars": stars
    }
    
    if stars and "_provenance" in stars[0]:
        data["provenance"] = stars[0]["_provenance"]

    if include_metadata:
        data["metadata"] = {
            "columns": [
                {"name": "source_id", "description": "Gaia DR3 Source ID", "type": "string"},
                {"name": "ra", "description": "Right Ascension (ICRS)", "type": "float", "unit": "deg"},
                {"name": "dec", "description": "Declination (ICRS)", "type": "float", "unit": "deg"},
                {"name": "parallax", "description": "Parallax", "type": "float", "unit": "mas"},
                {"name": "pmra", "description": "Proper motion RA", "type": "float", "unit": "mas/yr"},
                {"name": "pmdec", "description": "Proper motion Dec", "type": "float", "unit": "mas/yr"},
                {"name": "phot_g_mean_mag", "description": "Gaia G-band magnitude", "type": "float", "unit": "mag"},
                {"name": "bp_rp", "description": "BP - RP color index", "type": "float", "unit": "mag"},
                {"name": "ruwe", "description": "Renormalized Unit Weight Error", "type": "float"},
                {"name": "discovery_score", "description": "Anomaly score (higher = more interesting)", "type": "float"},
            ]
        }

    return json.dumps(data, indent=2)


def format_for_topcat(stars: List[Dict]) -> str:
    """Format output specifically optimized for TOPCAT compatibility.

    TOPCAT prefers either VOTable or CSV with proper column metadata.
    This function returns CSV with a header comment block.
    """
    comment = f"""# TaarYa Output for TOPCAT
# Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}
# Total Stars: {len(stars)}
#
# Column Descriptions:
#   source_id       - Gaia DR3 Source ID
#   ra              - Right Ascension (ICRS, degrees)
#   dec             - Declination (ICRS, degrees)
#   parallax        - Parallax (milliarcsec)
#   pmra            - Proper motion RA (mas/yr)
#   pmdec           - Proper motion Dec (mas/yr)
#   phot_g_mean_mag - Gaia G-band magnitude
#   phot_bp_mean_mag - Gaia BP-band magnitude
#   phot_rp_mean_mag - Gaia RP-band magnitude
#   bp_rp           - BP-RP color index
#   ruwe            - Renormalized Unit Weight Error
#   discovery_score - Anomaly score
#
"""

    csv_content = export_to_csv(stars)
    return comment + csv_content


def format_for_aladin(stars: List[Dict], filename: str = "taarya_output.vot") -> str:
    """Generate files specifically for Aladin sky atlas.

    Aladin supports VOTable directly. This creates a VOTable with
    additional columns that Aladin recognizes (POS_EQ_RA, POS_EQ_DEC).
    """
    aladin_stars = []
    for star in stars:
        s = star.copy()
        s["POS_EQ_RA"] = star.get("ra")
        s["POS_EQ_DEC"] = star.get("dec")
        aladin_stars.append(s)

    return export_to_votable(aladin_stars)
