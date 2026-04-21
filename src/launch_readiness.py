"""Launch-readiness validation command for the production slice."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

from src.extensions.taarya_ds9 import TaarYaDS9
from src.extensions.taarya_mesa import TaarYaMESA
from src.main import _readiness_payload, app
from src.retrieval.graph_search import GraphSearch
from src.retrieval.spatial_search import SpatialSearch
from src.utils.ner_extractor import NERExtractor


def _ok(name: str, details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {"name": name, "status": "pass", "details": details or {}}


def _fail(name: str, error: str, details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = {"name": name, "status": "fail", "error": error}
    if details:
        payload["details"] = details
    return payload


def _route_map() -> Dict[str, set[str]]:
    routes: Dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        routes[path] = set(methods)
    return routes


def _check_api_surface() -> Dict[str, Any]:
    required = {
        "/ready": "GET",
        "/api/papers/by-star/{source_id}": "GET",
        "/api/interop/ds9-regions": "GET",
        "/api/mesa/inlist/{source_id}": "GET",
        "/api/cone-search/export": "GET",
    }
    routes = _route_map()
    missing: List[str] = []
    for path, method in required.items():
        methods = routes.get(path, set())
        if method not in methods:
            missing.append(f"{method} {path}")
    if missing:
        return _fail("api_surface", "Missing required API routes", {"missing": missing})
    return _ok("api_surface", {"required_routes": len(required)})


def _check_deterministic_exports() -> Dict[str, Any]:
    try:
        ds9 = TaarYaDS9()
        content = ds9.render_region_file(
            [{"source_id": "123", "ra": 12.3, "dec": -4.5, "score": 16.2}]
        )
        if "DS9 version 4.1" not in content or "circle(12.3,-4.5,10.0\")" not in content:
            return _fail("scientific_exports", "DS9 render output did not match expected format")

        inlist = TaarYaMESA.build_inlist(
            {"source_id": "1234567890123456789", "teff_estimated_k": 6400}
        )
        if "initial_mass =" not in inlist or "Gaia source_id 1234567890123456789" not in inlist:
            return _fail("scientific_exports", "MESA inlist output missing required fields")

        extractor = NERExtractor()
        clusters = extractor.extract_cluster_mentions(
            "Targets in the Pleiades (M45) and Hyades were analysed."
        )
        if clusters != ["pleiades", "hyades"]:
            return _fail(
                "scientific_exports",
                "Deterministic cluster extraction order is not stable",
                {"observed": clusters},
            )

        return _ok("scientific_exports")
    except Exception as exc:
        return _fail("scientific_exports", str(exc))


def _check_spatial_and_graph(backends: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []

    if backends.get("postgresql", {}).get("status") == "connected":
        try:
            spatial = SpatialSearch()
            stars = spatial.cone_search(ra=56.75, dec=24.12, radius=0.15, limit=3)
            checks.append(_ok("spatial_flow", {"sample_count": len(stars)}))
        except Exception as exc:
            checks.append(_fail("spatial_flow", str(exc)))
    else:
        checks.append(_fail("spatial_flow", "PostgreSQL is not connected"))

    neo4j_status = backends.get("neo4j", {}).get("status")
    if neo4j_status == "connected":
        try:
            graph = GraphSearch()
            _ = graph.find_star_papers("0", include_cluster_context=True, limit=1)
            checks.append(_ok("graph_flow"))
        except Exception as exc:
            checks.append(_fail("graph_flow", str(exc)))
    elif neo4j_status == "starting":
         try:
             from src.database import neo4j_conn
             import time
             for _ in range(3):
                 time.sleep(2)
                 try:
                     neo4j_conn.connect()
                     with neo4j_conn.session() as session:
                         session.run("RETURN 1 AS ok").single()
                     checks.append(_ok("graph_flow", {"note": "Neo4j came up on retry"}))
                     backends["neo4j"] = {"status": "connected"}
                     break
                 except Exception:
                     pass
             else:
                 checks.append(_fail("graph_flow", "Neo4j container up but driver could not connect within 6s"))
         except Exception as exc:
             checks.append(_fail("graph_flow", str(exc)))
    else:
        checks.append(_fail("graph_flow", "Neo4j is not connected"))

    return checks


def run_launch_readiness() -> int:
    checks: List[Dict[str, Any]] = []

    backends_raw = _readiness_payload()
    backends = backends_raw.get("backends", {})

    neo4j_status = backends.get("neo4j", {}).get("status")
    if neo4j_status == "starting":
        try:
            from src.database import neo4j_conn
            import time
            for _ in range(3):
                time.sleep(2)
                try:
                    neo4j_conn.connect()
                    with neo4j_conn.session() as session:
                        session.run("RETURN 1 AS ok").single()
                    backends["neo4j"] = {"status": "connected"}
                    break
                except Exception:
                    pass
        except Exception:
            pass

    ready = all(
        info.get("status") == "connected"
        for info in backends.values()
    )
    backend_state = {"status": "degraded" if not ready else "ready", "ready": ready, "backends": backends}
    checks.append(
        _ok("backend_readiness", backend_state)
        if ready
        else _fail("backend_readiness", "One or more core backends are not connected", backend_state)
    )

    checks.append(_check_api_surface())
    checks.append(_check_deterministic_exports())
    checks.extend(_check_spatial_and_graph(backend_state.get("backends", {})))

    passed = sum(1 for item in checks if item["status"] == "pass")
    failed = len(checks) - passed
    summary = {
        "status": "ready" if failed == 0 else "not_ready",
        "passed": passed,
        "failed": failed,
        "checks": checks,
    }
    print(json.dumps(summary, indent=2))
    return 0 if failed == 0 else 1


def main() -> None:
    raise SystemExit(run_launch_readiness())


if __name__ == "__main__":
    main()
