import json, pytest
from pathlib import Path
from taarya_workflows.real.cone_sample_audit import audit_sample


def test_audit_sample_on_hr23_fixtures():
    # If hr23 files exist, verify audit_sample runs cleanly and returns valid structure
    cones_dir = "hr23/cones"
    selection_path = "hr23/selection.json"
    clusters_path = "hr23/clusters.csv"
    members_path = "hr23/selected_members.csv"

    if not Path(selection_path).exists():
        pytest.skip("hr23 fixtures not generated yet")

    rep = audit_sample(cones_dir, selection_path, clusters_path, members_path)
    assert rep["n_selected"] == 30
    assert len(rep["truncated_downloads"]) == 0
    assert rep["cut_uniformity"]["uniform"] is True
    assert len(rep["ok_clusters_audit"]) == 19
    assert len(rep["skipped_clusters_audit"]) == 6
    assert len(rep["member_prob_breakdown"]) == 5
    assert "compact open clusters in uncrowded fields within 1 kpc" in rep["sample_scope"]

