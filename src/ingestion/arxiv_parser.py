"""Parser for ArXiv papers (PDF extraction)."""
import logging
from pathlib import Path
from typing import Dict, Any, List
import re
from datetime import datetime

try:
    import pymupdf as fitz  # PyMuPDF
except ImportError:
    import fitz

logger = logging.getLogger(__name__)


class ArXivParser:
    """Parse ArXiv PDF papers and extract metadata + text."""
    
    def __init__(self):
        self.arxiv_id_pattern = re.compile(r'arXiv:(\d{4}\.\d{4,5})')
    
    def extract_arxiv_id(self, text: str) -> str:
        """Extract arXiv ID from text."""
        match = self.arxiv_id_pattern.search(text)
        if match:
            return match.group(1)
        return None
    
    def parse_pdf(self, filepath: Path) -> Dict[str, Any]:
        """
        Parse PDF and extract text + metadata.
        
        Args:
            filepath: Path to PDF file
            
        Returns:
            Dictionary with paper metadata and text
        """
        logger.info(f"Parsing PDF: {filepath}")
        
        doc = fitz.open(filepath)
        
        # Extract metadata
        metadata = doc.metadata
        
        # Extract text from all pages
        full_text = ""
        for page_num in range(len(doc)):
            page = doc[page_num]
            full_text += page.get_text()
        
        doc.close()
        
        # Try to extract arXiv ID from text
        arxiv_id = self.extract_arxiv_id(full_text[:5000])  # Check first 5000 chars
        
        if not arxiv_id:
            # Fallback: use filename if it looks like arXiv ID
            filename = filepath.stem
            if re.match(r'\d{4}\.\d{4,5}', filename):
                arxiv_id = filename
            else:
                logger.warning(f"Could not extract arXiv ID from {filepath}")
                arxiv_id = filepath.stem
        
        # Extract title (usually in metadata or first page)
        title = metadata.get('title', '')
        if not title:
            # Try to extract from first 500 chars
            lines = full_text[:500].split('\n')
            for line in lines:
                if len(line) > 20 and line[0].isupper():
                    title = line.strip()
                    break
        
        # Extract abstract (usually after "Abstract" keyword)
        abstract = self._extract_abstract(full_text)
        
        paper_data = {
            'arxiv_id': arxiv_id,
            'title': title[:500] if title else filepath.stem,
            'authors': metadata.get('author', ''),
            'abstract': abstract,
            'full_text': full_text,
            'categories': '',  # Will be populated from ArXiv API if available
            'published_date': metadata.get('creationDate', ''),
            'updated_date': metadata.get('modDate', ''),
        }
        
        logger.debug(f"Extracted: {arxiv_id} - {title[:50]}...")
        return paper_data
    
    def _extract_abstract(self, text: str) -> str:
        """Extract abstract from full text."""
        # Look for "Abstract" keyword
        abstract_pattern = re.compile(
            r'Abstract[:\s]+(.*?)(?:\n\n|\n[A-Z][a-z]+|1\s+Introduction)',
            re.DOTALL | re.IGNORECASE
        )
        
        match = abstract_pattern.search(text)
        if match:
            abstract = match.group(1).strip()
            return abstract[:2000]  # Limit length
        
        return ""
    
    def chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """
        Split text into overlapping chunks for embedding.
        
        Args:
            text: Full text to chunk
            chunk_size: Size of each chunk in characters
            overlap: Overlap between chunks
            
        Returns:
            List of text chunks
        """
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            
            # Try to break at sentence boundary
            if end < len(text):
                last_period = chunk.rfind('.')
                if last_period > chunk_size * 0.8:  # At least 80% of chunk size
                    end = start + last_period + 1
                    chunk = text[start:end]
            
            chunks.append(chunk.strip())
            start = end - overlap
        
        return chunks
