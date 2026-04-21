"""Scientific consistency checking between catalog data and literature."""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ScientificConsistency:
    """
    Checks if catalog signals (Gaia) are consistent with literature claims (ArXiv).
    
    This is a core novelty feature of TaarYa, providing a "scientific reasoning"
    layer that validates whether physical parameters match research context.
    """
    
    # Keywords that suggest specific physical phenomena in literature
    PHENOMENA_KEYWORDS = {
        "binary": ["binary", "double star", "companion", "orbit", "spectroscopic"],
        "young": ["young", "yso", "t tauri", "pre-main sequence", "protostar", "cluster member"],
        "variable": ["variable", "pulsating", "cepheid", "rr lyrae", "flare"],
        "high_motion": ["high proper motion", "runaway", "hypervelocity", "nearby"],
        "metal_poor": ["metal-poor", "halo", "ancient", "population ii"],
    }

    def check_star_paper_consistency(self, star: Dict[str, Any], paper: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if a star's Gaia parameters are consistent with a paper's abstract.
        
        Args:
            star: Gaia star record (with RUWE, color, motion)
            paper: ArXiv paper record (with title, abstract)
            
        Returns:
            Consistency report with score and reasons
        """
        abstract = (paper.get("abstract", "") + " " + paper.get("title", "")).lower()
        ruwe = star.get("ruwe")
        bp_rp = star.get("bp_rp")
        pm = star.get("pm")
        
        consistency_score = 0.0
        matches = []
        conflicts = []
        
        # 1. Binary/Companion Consistency (RUWE)
        if any(k in abstract for k in self.PHENOMENA_KEYWORDS["binary"]):
            if ruwe is not None:
                if ruwe > 1.4:
                    consistency_score += 0.4
                    matches.append(f"Literature mentions 'binary'; Gaia RUWE {ruwe:.2f} is consistent (high).")
                else:
                    consistency_score -= 0.2
                    conflicts.append(f"Literature mentions 'binary'; Gaia RUWE {ruwe:.2f} is low (nominal).")
        
        # 2. High Motion Consistency
        if any(k in abstract for k in self.PHENOMENA_KEYWORDS["high_motion"]):
            if pm is not None:
                if pm > 50: # mas/yr
                    consistency_score += 0.4
                    matches.append(f"Literature mentions 'high motion'; Gaia PM {pm:.2f} mas/yr is consistent.")
                else:
                    consistency_score -= 0.2
                    conflicts.append(f"Literature mentions 'high motion'; Gaia PM {pm:.2f} mas/yr is low.")
                    
        # 3. Young Star Consistency (Color)
        if any(k in abstract for k in self.PHENOMENA_KEYWORDS["young"]):
            if bp_rp is not None:
                if bp_rp > 1.5: # Typically redder
                    consistency_score += 0.3
                    matches.append(f"Literature mentions 'young/YSO'; Gaia BP-RP {bp_rp:.2f} is consistent (red).")
                elif bp_rp < 0.5: # Or very blue
                    consistency_score += 0.3
                    matches.append(f"Literature mentions 'young/YSO'; Gaia BP-RP {bp_rp:.2f} is consistent (blue).")

        return {
            "source_id": star.get("source_id"),
            "arxiv_id": paper.get("arxiv_id"),
            "consistency_score": round(max(-1.0, min(1.0, consistency_score)), 2),
            "matches": matches,
            "conflicts": conflicts,
            "status": "consistent" if consistency_score > 0 else "uncertain" if consistency_score == 0 else "conflicting"
        }

    def batch_consistency_check(self, stars: List[Dict[str, Any]], papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run consistency checks for all star-paper pairs."""
        reports = []
        for star in stars:
            for paper in papers:
                reports.append(self.check_star_paper_consistency(star, paper))
        return reports
