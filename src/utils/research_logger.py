"""Research provenance and reproducibility logger."""

import datetime
import hashlib
import json
import logging
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import settings

logger = logging.getLogger(__name__)


class ResearchProvenanceLogger:
    """
    Logs all scientific actions to a session-specific manifest.
    Ensures that every discovery can be traced back to the exact parameters.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = Path("eval") / "sessions" / self.session_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.log_dir / "manifest.json"
        self.actions: List[Dict[str, Any]] = []
        self._init_manifest()

    def _init_manifest(self) -> None:
        env_info = {
            "session_id": self.session_id,
            "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "system": f"TaarYa-v{self._get_app_version()}-research",
            "environment_hash": self._get_env_hash(),
            "llm_model": getattr(settings, "ollama_model", "unknown"),
            "embedding_model": settings.embedding_model,
            "backends": {
                "postgresql": {"host": settings.postgres_host, "db": settings.postgres_db},
                "qdrant": {"host": settings.qdrant_host, "port": settings.qdrant_port},
                "neo4j": {"uri": settings.neo4j_uri},
            },
            "actions": [],
        }
        with open(self.manifest_path, "w") as f:
            json.dump(env_info, f, indent=2)

    def _get_app_version(self) -> str:
        try:
            from importlib.metadata import version
            return version("taarya")
        except Exception:
            return "0.2.0"

    def _get_env_hash(self) -> str:
        try:
            with open("pyproject.toml", "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
        except Exception:
            return "unknown"

    def log_action(
        self,
        action_type: str,
        parameters: Dict[str, Any],
        results_summary: str,
        tags: Optional[List[str]] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "type": action_type,
            "params": parameters,
            "summary": results_summary,
            "tags": tags or [],
        }
        self.actions.append(entry)
        try:
            with open(self.manifest_path, "r") as f:
                manifest = json.load(f)
            manifest["actions"].append(entry)
            with open(self.manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
            logger.info(f"Provenance logged: {action_type}")
        except Exception as e:
            logger.error(f"Failed to log provenance: {e}")

    def log_discovery(
        self,
        source_id: str,
        score: float,
        reasons: List[str],
        ra: float,
        dec: float,
        params: Dict[str, Any],
    ) -> None:
        self.log_action(
            "discovery_candidate",
            {
                "source_id": source_id,
                "ra": ra,
                "dec": dec,
                "discovery_score": score,
                "scoring_params": params,
            },
            f"Star {source_id} flagged with score {score:.2f}: {', '.join(reasons)}",
            tags=["discovery", "anomaly"],
        )

    def export_session_bundle(self, results_dir: Optional[Path] = None) -> Path:
        """
        Create a zip archive of the session manifest and any results in results_dir.

        The bundle is suitable for attachment to a publication or sharing with
        collaborators for reproducibility verification.
        """
        results_dir = Path(results_dir) if results_dir else self.log_dir
        bundle_path = self.log_dir / f"session_{self.session_id}.zip"

        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest_file = self.log_dir / "manifest.json"
            if manifest_file.exists():
                zf.write(manifest_file, arcname="manifest.json")

            for file_path in results_dir.glob("*"):
                if file_path.is_file() and file_path != manifest_file:
                    zf.write(file_path, arcname=f"results/{file_path.name}")

        logger.info(f"Provenance bundle written to {bundle_path}")
        return bundle_path

    def get_manifest(self) -> Dict[str, Any]:
        try:
            with open(self.manifest_path) as f:
                return json.load(f)
        except Exception:
            return {"session_id": self.session_id, "actions": []}
