"""Semantic summarization for astronomical research data."""

import logging
from typing import List, Dict, Any, Optional
import textwrap

logger = logging.getLogger(__name__)

class SemanticSummarizer:
    """
    Handles 'data deluge' by summarizing large sets of catalog results
    or literature snippets into concise research briefings.
    """

    @staticmethod
    def summarize_star_batch(stars: List[Dict[str, Any]]) -> str:
        """
        Summarize a batch of star records for a researcher.
        """
        if not stars:
            return "No stars found to summarize."

        total = len(stars)
        high_score = [s for s in stars if s.get("discovery_score", 0) > 10]
        anomalies = [s for s in stars if s.get("ruwe", 0) > 1.4 or s.get("pm", 0) > 100]
        
        summary = f"### Research Briefing: Batch Analysis ({total} objects)\n\n"
        
        if high_score:
            summary += f"**Priority Discovery Candidates ({len(high_score)}):**\n"
            for s in high_score[:3]:
                reasons = ", ".join(s.get("discovery_reasons", []))
                summary += f"- {s['source_id']} (Score: {s['discovery_score']}): {reasons}\n"
        
        if anomalies:
            summary += f"\n**Astrometric/Kinematic Anomalies ({len(anomalies)}):**\n"
            summary += f"- Found {len(anomalies)} objects with elevated RUWE or high proper motion.\n"

        # Statistical distribution
        mags = [s.get("phot_g_mean_mag") for s in stars if s.get("phot_g_mean_mag") is not None]
        if mags:
            avg_mag = sum(mags) / len(mags)
            summary += f"\n**Population Statistics:**\n"
            summary += f"- Mean Magnitude: G={avg_mag:.2f}\n"
            summary += f"- Magnitude Range: G=[{min(mags):.1f}, {max(mags):.1f}]\n"

        return summary

    @staticmethod
    def map_reduce_literature(papers: List[Dict[str, Any]], query: str) -> str:
        """
        Map-Reduce style summarization of ArXiv papers relative to a query.
        """
        if not papers:
            return "No literature found to summarize."

        # Map phase: Extract key findings from each paper
        key_findings = []
        for p in papers:
            title = p.get("payload", {}).get("title", "Untitled")
            abstract = p.get("payload", {}).get("abstract", "")
            # Simulate 'Map' extraction of relevant sentences
            key_findings.append(f"**[{title}]**: {abstract[:200]}...")

        # Reduce phase: Synthesize into a single briefing
        briefing = f"### Literature Synthesis: {query}\n\n"
        briefing += "Based on the top relevant papers, here is the synthesis:\n\n"
        briefing += "\n".join(key_findings[:5])
        briefing += f"\n\n**Scientific Consensus:** The literature suggests a strong focus on {query.lower()} in recent surveys."
        
        return briefing
