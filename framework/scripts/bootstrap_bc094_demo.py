#!/usr/bin/env python3
"""Administrator bootstrap for the isolated BC-094 business-agent demo registry."""
import json
import os
from pathlib import Path

from aimec_capability_registry import PersistentCapabilityRegistry


BUILTINS = {
    "business-diagnostics.tool.json": "aimec.business-diagnostics",
    "ai-opportunity-analyst.agent.json": "aimec.ai-opportunity-analyst",
    "ai-solution-architect.agent.json": "aimec.ai-solution-architect",
}


def _check_boundary(manifest):
    cid = manifest["identity"]["id"]
    actions = set(manifest["permissions"]["actions"])
    if (
        actions - {"read", "analyze", "delegate"}
        or manifest["permissions"]["filesystem"] != "none"
        or manifest["risk"]["irreversible"]
        or manifest["credentials"]["required"]
        or manifest["data_policy"]["input_classes"] != ["public"]
    ):
        raise ValueError("business demo builtin permission boundary changed")
    if manifest["kind"] == "tool":
        if manifest["permissions"]["network"] != "none" or manifest["delegation"]["can_delegate"]:
            raise ValueError("business tool boundary changed")
    else:
        if manifest["permissions"]["network"] != "restricted":
            raise ValueError("business agents may only use restricted local-model networking")
        if cid == "aimec.ai-opportunity-analyst":
            if not manifest["delegation"]["can_delegate"] or manifest["delegation"]["max_hops"] != 1:
                raise ValueError("analyst handoff boundary changed")
        elif manifest["delegation"]["can_delegate"] or manifest["delegation"]["max_hops"] != 0:
            raise ValueError("architect onward-delegation boundary changed")


def bootstrap(path, manifest_dir):
    registry = PersistentCapabilityRegistry(path)
    allowed_ids = set(BUILTINS.values())
    if set(registry.records) - allowed_ids:
        raise ValueError("refusing to bootstrap a non-BC094 demo registry")
    for filename, expected_id in BUILTINS.items():
        manifest = json.loads((Path(manifest_dir) / filename).read_text())
        if manifest["identity"]["id"] != expected_id:
            raise ValueError("business demo manifest identity changed")
        _check_boundary(manifest)
        existing = registry.records.get(expected_id)
        registry.submit(manifest)
        if existing is None:
            registry.decide(expected_id, reviewer="admin:bc094-isolated-demo-bootstrap", approved=True)
        elif existing.status != "approved":
            raise ValueError("existing non-approved record requires explicit administrator review")
    return {
        "ok": True,
        "approved_builtins": sorted(registry.records),
        "external_business_actions_enabled": False,
        "local_llm_required": True,
    }


if __name__ == "__main__":
    if os.getenv("AIMEC_ISOLATED_DEMO_BOOTSTRAP") != "1":
        raise SystemExit("Explicit isolated-demo bootstrap mode is required")
    print(json.dumps(bootstrap(os.environ["AIMEC_CAPABILITY_REGISTRY_DB"], "/app/manifests")))
