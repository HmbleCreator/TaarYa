"""Parser for Gaia catalog data (CSV/FITS formats)."""
import logging
from pathlib import Path
from typing import Iterator, Dict, Any
import pandas as pd


logger = logging.getLogger(__name__)


class GaiaParser:
    """Parse Gaia DR3 catalog files (CSV or FITS)."""
    
    # Gaia DR3 field mapping to our schema
    FIELD_MAPPING = {
        'source_id': 'source_id',
        'SOURCE_ID': 'source_id',  # Gaia CSV uses uppercase
        'ra': 'ra',
        'dec': 'dec',
        'parallax': 'parallax',
        'parallax_error': 'parallax_error',
        'pmra': 'pmra',
        'pmdec': 'pmdec',
        'phot_g_mean_mag': 'phot_g_mean_mag',
        'phot_bp_mean_mag': 'phot_bp_mean_mag',
        'phot_rp_mean_mag': 'phot_rp_mean_mag',
        'ruwe': 'ruwe',
    }
    
    def __init__(self, chunk_size: int = 10000):
        """
        Initialize Gaia parser.
        
        Args:
            chunk_size: Number of rows to process at a time
        """
        self.chunk_size = chunk_size
    
    def parse_csv(self, filepath: Path) -> Iterator[pd.DataFrame]:
        """
        Parse Gaia CSV file in chunks.
        
        Args:
            filepath: Path to CSV file
            
        Yields:
            DataFrame chunks with standardized columns
        """
        logger.info(f"Parsing CSV: {filepath}")
        
        for chunk in pd.read_csv(filepath, chunksize=self.chunk_size):
            # Rename columns to match our schema
            chunk = chunk.rename(columns=self.FIELD_MAPPING)
            
            # Select only mapped columns
            available_cols = [col for col in self.FIELD_MAPPING.values() if col in chunk.columns]
            chunk = chunk[available_cols]
            
            # Add catalog source
            chunk['catalog_source'] = 'GAIA'
            
            # Convert source_id to string
            if 'source_id' in chunk.columns:
                chunk['source_id'] = chunk['source_id'].astype(str)
            
            # Replace NaN with None for proper SQL NULLs
            chunk = chunk.where(chunk.notna(), None)
            
            logger.debug(f"Parsed chunk: {len(chunk)} rows")
            yield chunk
    
    def parse_fits(self, filepath: Path) -> Iterator[Dict[str, Any]]:
        """
        Parse Gaia FITS file.
        
        Args:
            filepath: Path to FITS file
            
        Yields:
            Star records as dictionaries
        """
        logger.info(f"Parsing FITS: {filepath}")
        
        
        from astropy.io import fits
        from astropy.table import Table
        
        with fits.open(filepath) as hdul:
            table = Table(hdul[1].data)
            
            # Convert to pandas for easier processing
            df = table.to_pandas()
            
            # Rename columns
            df = df.rename(columns=self.FIELD_MAPPING)
            
            # Process in chunks
            for start in range(0, len(df), self.chunk_size):
                chunk = df.iloc[start:start + self.chunk_size]
                
                # Select only mapped columns
                available_cols = [col for col in self.FIELD_MAPPING.values() if col in chunk.columns]
                chunk = chunk[available_cols]
                
                # Add catalog source
                chunk['catalog_source'] = 'GAIA'
                
                logger.debug(f"Parsed chunk: {len(chunk)} rows")
                yield chunk
    
    def parse(self, filepath: Path) -> Iterator[pd.DataFrame]:
        """
        Auto-detect format and parse.
        
        Args:
            filepath: Path to catalog file
            
        Yields:
            DataFrame chunks
        """
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        suffix = filepath.suffix.lower()
        
        if suffix == '.csv':
            yield from self.parse_csv(filepath)
        elif suffix in ['.fits', '.fit']:
            yield from self.parse_fits(filepath)
        else:
            raise ValueError(f"Unsupported format: {suffix}")
