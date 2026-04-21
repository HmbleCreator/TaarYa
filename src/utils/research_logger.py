"""Research provenance and reproducibility logger."""

import json
import logging
import os
import datetime
import hashlib
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class ResearchProvenanceLogger:
    """
    Logs all scientific actions to a session-specific manifest.
    Ensures that every discovery can be traced back to the exact parameters.
    """

    def __init__(self, session_id: str = None):
        self.session_id = session_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = os.path.join("eval", "sessions", self.session_id)
        os.makedirs(self.log_dir, exist_ok=True)
        self.manifest_path = os.path.join(self.log_dir, "manifest.json")
        self.actions = []
        self._init_manifest()

    def _init_manifest(self):
        """Initialize the manifest with system environment info."""
        env_info = {
            "session_id": self.session_id,
            "start_time": datetime.datetime.utcnow().isoformat(),
            "system": "TaarYa-v0.2.0-research",
            "environment_hash": self._get_env_hash(),
            "actions": []
        }
        with open(self.manifest_path, 'w') as f:
            json.dump(env_info, f, indent=2)

    def _get_env_hash(self) -> str:
        """Create a hash of the current code state (pyproject.toml)."""
        try:
            with open("pyproject.toml", "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except:
            return "unknown"

    def log_action(self, action_type: str, parameters: Dict[str, Any], results_summary: str):
        """Log a scientific action to the manifest."""
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "type": action_type,
            "params": parameters,
            "summary": results_summary
        }
        
        # Load, update, and save
        try:
            with open(self.manifest_path, 'r') as f:
                manifest = json.load(f)
            
            manifest["actions"].append(entry)
            
            with open(self.manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)
                
            logger.info(f"Provenance logged: {action_type}")
        except Exception as e:
            logger.error(f"Failed to log provenance: {e}")

    def export_session_bundle(self):
        """Create a zip of the manifest and results for publication attachment."""
        # Implementation for zipping the log_dir
        pass
