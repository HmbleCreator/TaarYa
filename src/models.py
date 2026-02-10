"""Database models for astronomical data."""
from sqlalchemy import Column, Integer, Float, String, Text, Index, func
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Star(Base):
    """Star catalog entry from Gaia/SIMBAD."""
    
    __tablename__ = "stars"
    
    # Primary identifier
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(50), unique=True, index=True, nullable=False)
    
    # Coordinates (J2000)
    ra = Column(Float, nullable=False, doc="Right Ascension in degrees")
    dec = Column(Float, nullable=False, doc="Declination in degrees")
    
    # Astrometric parameters
    parallax = Column(Float, doc="Parallax in milliarcseconds")
    parallax_error = Column(Float)
    pmra = Column(Float, doc="Proper motion in RA (mas/yr)")
    pmdec = Column(Float, doc="Proper motion in Dec (mas/yr)")
    
    # Photometric data
    phot_g_mean_mag = Column(Float, doc="G-band mean magnitude")
    phot_bp_mean_mag = Column(Float, doc="BP-band mean magnitude")
    phot_rp_mean_mag = Column(Float, doc="RP-band mean magnitude")
    
    # Quality flags
    ruwe = Column(Float, doc="Renormalized unit weight error")
    
    # Catalog metadata
    catalog_source = Column(String(20), default="GAIA", doc="Source catalog")
    
    # Indexes for Q3C spatial queries
    __table_args__ = (
        Index('idx_q3c_stars', 'ra', 'dec'),  # Standard composite index
        Index('idx_q3c_ipix', func.q3c_ang2ipix(ra, dec)),  # Q3C spatial index
    )


class Paper(Base):
    """ArXiv paper metadata."""
    
    __tablename__ = "papers"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    arxiv_id = Column(String(50), unique=True, index=True, nullable=False)
    title = Column(String(500), nullable=False)
    authors = Column(Text)
    abstract = Column(Text)
    categories = Column(String(200))
    published_date = Column(String(20))
    updated_date = Column(String(20))
    
    # For vector search reference
    qdrant_collection = Column(String(50), default="papers")
    qdrant_point_ids = Column(Text, doc="JSON array of Qdrant point IDs for chunks")


class ObservationMetadata(Base):
    """Additional observational metadata."""
    
    __tablename__ = "observations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    star_id = Column(Integer, index=True)
    observation_time = Column(String(50))
    telescope = Column(String(100))
    wavelength_band = Column(String(50))
    notes = Column(Text)
