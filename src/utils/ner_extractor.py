"""Deterministic astronomical entity extraction with optional SIMBAD resolution."""

import logging
import re
from typing import Dict, List, Optional

from src.utils.simbad_validation import query_simbad_by_name

try:
    from astropy.coordinates import SkyCoord
    import astropy.units as u
except ImportError:
    SkyCoord = None
    u = None

logger = logging.getLogger(__name__)

GAIA_NAME_PATTERN = re.compile(
    r"\bGaia(?:\s+DR[23])?(?:\s+source(?:\s*id)?)?\s+(\d{18,20})\b",
    re.IGNORECASE,
)
CATALOG_PATTERNS = (
    re.compile(r"\b(?:HD|HIP|HR|TIC|TYC|GJ|GL|LHS|LSPM)\s*[A-Z0-9.+\-]+\b", re.IGNORECASE),
    re.compile(r"\b2MASS\s+J\d{6,8}[+-]\d{6,8}\b", re.IGNORECASE),
    re.compile(r"\bBD[+\-]\d{1,2}\s+\d+[A-Z]?\b", re.IGNORECASE),
    re.compile(r"\bCD[+\-]\d{1,2}\s+\d+[A-Z]?\b", re.IGNORECASE),
)
COMMON_STAR_NAMES = frozenset({
    "Acamar", "Acrab", "Acrux", "Adhara", "Albireo", "Alcyone", "Aldebaran", "Algedi",
    "Algenib", "Algol", "Alhena", "Alioth", "Alkaid", "Alphard", "Alphecca", "Alpheratz",
    "Alnilam", "Alnitak", "Alpha Centauri", "Alphard", "Alpherg", "Altair", "Aludra",
    "Ancha", "Ankaa", "Antares", "Arcturus", "Arneb", "Ascella", "Ascellus",
    "Aspidiske", "Atria", "Avior", "Azelfafage", "Azha", "Baten Kaitos", "Beid",
    "Bellatrix", "Betelgeuse", "Biham", "Boraphel", "Brachium", "Bunda",
    "Canopus", "Capella", "Caph", "Castor", "Cebalrai", "Ceos", "Chara",
    "Cheleb", "Chertan", "Cornelia", "Coronae", "Corvus", "Cursa",
    "Dabih", "Decrux", "Deneb", "Denebola", "Diphda", "Dnoces", "Dschubba",
    "Dubhe", "Edasich", "Electra", "Elgendi", "Elnath", "Enif", "Errai",
    "Fomalhaut", "Fumalsamakah",
    "Gacrux", "Garnet Star", "Gemma", "Giausar", "Gienah", "Girtab",
    "Hadar", "Haedus", "Haldus", "Hamal", "Hassaleh", "Heka", "Heze",
    "Homan", "Ikarus", "Izar",
    "Jabbah", "Jih",
    "Kaffaljidima", "Kaus Australis", "Kaus Borealis", "Kaus Media", "Kaveh",
    "Keid", "Kitalpha", "Kornephoros", "Kuma", "Kwannot",
    "Lesath", "Maasym", "Mahasim", "Maia", "Marfik", "Markab", "Matar",
    "Mebsuta", "Megrez", "Meissa", "Mekbuda", "Menkab", "Menkar", "Menkent",
    "Merak", "Mimosa", "Minchir", "Minelauva", "Mira", "Mirach", "Miram",
    "Mirzam", "Mizar", "Muphrid", "Muscida",
    "Naos", "Nashira", "Nekkar", "Nihal", "Nunki",
    "Oechslar", "Okul", "Peacock", "Phact", "Phad", "Phecda", "Pherkad",
    "Polaris", "Pollux", "Porrima", "Procyon", "Propus", "Proxima Centauri",
    "Rasalhague", "Raselt", "Rasgit", "Rastaban", "Regulus", "Rigel", "Rigil Kent",
    "Rukbat",
    "Sabik", "Sadalbari", "Sadalsuud", "Sadalmelik", "Sadalsud", "Sadr",
    "Saiph", "Sarin", "Sceptrum", "Scha", "Schedar", "Sci", "Segin",
    "Seginus", "Sham", "Shaula", "Sheliak", "Sheratan", "Sualocin", "Subra",
    "Suhail", "Sulafat", "Supercellum", "Syrma",
    "Talitha", "Tau Ceti", "Taygeta", "Tegmen", "Tejat", "Thabit",
    "Theemin", "Toliman", "Trappist-1", "Tyth",
    "Unukalhai", "Vega", "Vindemiatrix", "Wasat", "Wazn", "Wezn",
    "Xamidimura", "Xi Scorpii",
    "Yed Prior", "Yed Posterior", "Yildun",
    "Zaniah", "Zaurak", "Zavijava", "Zedaron", "Zel Phyll", "Zeta Reticuli",
    "Zubenelakrab", "Zubenelgenubi", "Zubeneschamali", "Zubenobj",
    "Alpherg", "Alcyone", "Caph", "Diphda", "Fomalhaut", "Mimosa", "Naos",
    "Peacock", "Sargas", "Sirius", "Suhail", "Tau Ceti", "Thabit", "Unukalhai",
    "Vega", "Wezn", "Zaniah",
})

LOCAL_COORDINATES: dict = {
    "sirius":          {"ra": 101.287, "dec": -16.716},
    "vega":            {"ra": 279.235, "dec": 38.784},
    "arcturus":        {"ra": 213.915, "dec": 19.182},
    "capella":         {"ra": 79.815, "dec": 45.998},
    "rigel":           {"ra": 78.634, "dec": -8.202},
    "proxima centauri": {"ra": 217.405, "dec": -62.669},
    "betelgeuse":      {"ra": 88.793, "dec": 7.407},
    "antares":         {"ra": 247.352, "dec": -26.432},
    "aldebaran":       {"ra": 68.980, "dec": 16.509},
    "spica":           {"ra": 201.298, "dec": -11.161},
    "pollux":          {"ra": 116.329, "dec": 28.026},
    "fomalhaut":       {"ra": 344.413, "dec": -29.622},
    "deneb":           {"ra": 310.358, "dec": 45.280},
    "regulus":         {"ra": 152.093, "dec": 11.967},
    "altair":          {"ra": 297.696, "dec": 8.868},
    "canopus":         {"ra": 95.988, "dec": -52.696},
    "arcturus":        {"ra": 213.915, "dec": 19.182},
    "polaris":         {"ra": 37.952, "dec": 89.264},
    "hadar":           {"ra": 210.956, "dec": -60.373},
    "beta centauri":   {"ra": 210.956, "dec": -60.373},
    "alpha centauri":  {"ra": 219.902, "dec": -60.835},
    "barnard's star":  {"ra": 269.454, "dec": 4.693},
    "wolf 359":        {"ra": 164.357, "dec": 7.017},
    "lalande 21185":  {"ra": 165.182, "dec": 35.971},
    "sirius a":        {"ra": 101.287, "dec": -16.716},
    "vega":            {"ra": 279.235, "dec": 38.784},
    "procyon":          {"ra": 114.826, "dec": 5.225},
    "tau ceti":        {"ra": 26.017, "dec": -15.938},
    "eta cassiop":     {"ra": 14.188, "dec": 57.815},
    "epsilon eridani": {"ra": 48.069, "dec": -9.458},
    "epsilon indi":    {"ra": 330.862, "dec": -56.788},
    "trappist-1":       {"ra": 346.525, "dec": -5.092},
    "kepler-442":      {"ra": 285.580, "dec": -1.616},
}
CLUSTER_ALIASES = {
    "hyades": ("hyades", "melotte 25", "collinder 50", "cr 50"),
    "pleiades": ("pleiades", "melotte 45", "m45", "seven sisters", "ngc 1432"),
    "orion ob1": ("orion ob1", "orion ob", "orion association", "orion moving group"),
    "coma berenices": ("coma berenices", "coma ber", "melotte 111", "ngc 5024", "ngc 5053"),
    "praesepe": ("praesepe", "m44", "ngc 2632", "beehive cluster", "melotte 121"),
    "ngc 2516": ("ngc 2516", "ngc2516", "spotted cluster"),
    "alpha per": ("alpha per", "alpha persei", "ngc 7092", "m34"),
    "ic 2391": ("ic 2391", "ic2391", "omicron velorum cluster", "sharpless 308"),
    "lmc": ("lmc", "large magellanic cloud", "nubecula major", "ngc 292"),
    "smc": ("smc", "small magellanic cloud", "nubecula minor", "ngc 292"),
    "omega centauri": ("omega centauri", "ngc 5139", "omega cen", "ω cen"),
    "galactic center": ("galactic center", "sagittarius a*", "sgr a*", "galactic centre"),
}


COMPONENT_SUFFIX_PATTERN = re.compile(
    r"(?<!\w)[ _-]?(?:[ABCabc][1-6]?|[IVX]+|[1-6])$"
)


def _strip_suffix(name: str) -> str:
    return COMPONENT_SUFFIX_PATTERN.sub("", name).strip()


def _dedupe_keep_order(items: List[str]) -> List[str]:
    """Return unique strings while preserving their original order."""
    seen = set()
    ordered: List[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return ordered


class NERExtractor:
    """Extract and resolve astronomical entities from paper text."""

    def __init__(self):
        self._spatial = None

    @property
    def spatial(self):
        """Lazy-load the spatial backend only when coordinate resolution is needed."""
        if self._spatial is None:
            from src.retrieval.spatial_search import SpatialSearch

            self._spatial = SpatialSearch()
        return self._spatial

    def extract_gaia_source_ids(self, text: str) -> List[str]:
        """Extract explicitly referenced Gaia IDs."""
        if not text:
            return []
        return _dedupe_keep_order([match.group(1) for match in GAIA_NAME_PATTERN.finditer(text)])

    def extract_cluster_mentions(self, text: str) -> List[str]:
        """Extract known cluster aliases so they can be handled separately."""
        if not text:
            return []

        hits = []
        for canonical_name, aliases in CLUSTER_ALIASES.items():
            for alias in aliases:
                pattern = rf"(?<!\w){re.escape(alias)}(?!\w)"
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if match:
                    hits.append((match.start(), canonical_name))
                    break
        ordered = [canonical_name for _, canonical_name in sorted(hits, key=lambda item: item[0])]
        return _dedupe_keep_order(ordered)

    def extract_names(self, text: str) -> List[str]:
        """Extract likely stellar identifiers without relying on an LLM."""
        if not text or len(text.strip()) < 8:
            return []

        names: List[str] = []
        for pattern in CATALOG_PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group(0).strip()
                stripped = _strip_suffix(raw)
                names.append(raw)
                if stripped != raw and stripped in COMMON_STAR_NAMES:
                    names.append(stripped)

        for star_name in COMMON_STAR_NAMES:
            pattern = rf"(?<!\w){re.escape(star_name)}(?!\w)"
            if re.search(pattern, text, flags=re.IGNORECASE):
                names.append(star_name)

        return _dedupe_keep_order(names)[:12]

    def resolve_local_coordinates(self, name: str) -> Optional[Dict[str, float]]:
        """Try local coordinate lookup before hitting SIMBAD."""
        key = name.strip().lower()
        for star_key, coords in LOCAL_COORDINATES.items():
            if key == star_key:
                return coords
        return None

    def resolve_to_source_ids(self, names: List[str]) -> List[str]:
        """Resolve names to local Gaia source IDs via local map, then SIMBAD."""
        if not names:
            return []

        cluster_names = {n.casefold() for n in self.extract_cluster_mentions(" ".join(names))}
        source_ids: List[str] = []

        for name in names:
            normalized = name.strip()
            if normalized.isdigit() and len(normalized) >= 18:
                source_ids.append(normalized)
                continue
            if normalized.casefold() in cluster_names:
                continue

            coords = self.resolve_local_coordinates(normalized)
            if coords is not None:
                try:
                    matches = self.spatial.cone_search(
                        ra=coords["ra"],
                        dec=coords["dec"],
                        radius=5.0,
                        unit="arcsec",
                        limit=1,
                    )
                    if matches:
                        source_ids.append(matches[0]["source_id"])
                        logger.info(f"Resolved '{normalized}' locally to Gaia {matches[0]['source_id']}")
                        continue
                except Exception:
                    pass

            simbad_obj = query_simbad_by_name(normalized)
            if not simbad_obj:
                continue

            try:
                if not SkyCoord or not u:
                    logger.debug("Astropy not available; skipping SIMBAD coordinate resolution.")
                    continue

                ra_str = simbad_obj.get("ra")
                dec_str = simbad_obj.get("dec")
                if not ra_str or not dec_str:
                    continue

                ra_str = " ".join(str(ra_str).split())
                dec_str = " ".join(str(dec_str).split())
                coord = SkyCoord(ra_str, dec_str, unit=(u.hourangle, u.deg))

                matches = self.spatial.cone_search(
                    ra=coord.ra.deg,
                    dec=coord.dec.deg,
                    radius=5.0,
                    unit="arcsec",
                    limit=1,
                )
                if matches:
                    source_ids.append(matches[0]["source_id"])
                    logger.info(f"Resolved '{normalized}' via SIMBAD to Gaia {matches[0]['source_id']}")
            except Exception as exc:
                logger.warning(f"Failed to resolve name '{normalized}': {exc}")

        return _dedupe_keep_order(source_ids)

    def process_text(self, text: str) -> List[str]:
        """Resolve a paper snippet into local Gaia source IDs."""
        direct_ids = self.extract_gaia_source_ids(text)
        candidate_names = self.extract_names(text)
        resolved_ids = self.resolve_to_source_ids(candidate_names) if candidate_names else []
        return _dedupe_keep_order(direct_ids + resolved_ids)
