from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
os.environ["AIMEC_BUSINESS_MANIFEST_DIR"] = str(ROOT / "registry" / "capabilities")
sys.path.insert(0, str(ROOT / "common"))
sys.path.insert(0, str(ROOT / "services" / "business_advisory"))

import capability


class BusinessDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.scenario = {
            "business_problem": "Synthetic invoice-processing opportunity.",
            "roi": {"employees": 5, "hours_per_week": 20, "hourly_cost": 32, "automation_percentage": 65, "implementation_cost": 18000},
            "cost": {"users": 8, "requests_per_user_per_day": 75, "tokens_per_request": 2600, "cost_per_million_tokens": 0.35, "monthly_infrastructure_cost": 450},
            "data_readiness": {"crm_data_quality": 4, "documentation_quality": 2, "api_availability": 4, "data_accuracy": 4, "security_controls": 3, "data_ownership": 3},
            "agentic_readiness": {"api_access": 4, "process_repeatability": 4, "approval_points": 3, "knowledge_documentation": 2, "business_data_access": 4, "automation_maturity": 3},
            "ai_readiness": {"strategy_clarity": 3, "data_quality_accessibility": 4, "process_documentation": 2, "tools_integrations": 4, "security_privacy": 3, "team_readiness": 3},
        }

    def test_roi_and_cost_are_deterministic(self):
        roi = capability.calculate_ai_roi(self.scenario["roi"])
        self.assertEqual(roi["annual_labor_cost"], 166400.0)
        self.assertEqual(roi["annual_gross_savings"], 108160.0)
        cost = capability.estimate_ai_cost(self.scenario["cost"])
        self.assertEqual(cost["monthly_total_cost"], 466.38)
        self.assertEqual(cost["annual_total_cost"], 5596.56)

    def test_readiness_exposes_low_scoring_gaps(self):
        result = capability.assess_data_readiness(self.scenario["data_readiness"])
        self.assertEqual(result["score"], 67)
        self.assertEqual(result["band"], "developing")
        self.assertIn("Internal documentation quality", result["priority_gaps"])

    def test_full_flow_uses_two_model_roles_and_recalculates_roi(self):
        analyst_json = {"opportunity": "AI-assisted invoice processing", "priority": "HIGH", "rationale": "The labor opportunity is material and the API baseline is workable.", "risks": ["Process documentation is incomplete"], "recommendation": "PILOT"}
        architect_json = {"architecture_summary": "Use document extraction, a grounded workflow and ERP actions behind approval.", "components": ["Document extraction", "Knowledge retrieval", "ERP adapter"], "human_approval_points": ["Approve low-confidence invoice matches"], "phases": [{"phase": "1", "name": "Pilot", "outcome": "Measure extraction and matching accuracy"}], "implementation_notes": "Start read-only, then add controlled writes."}
        def fake_llm(system_prompt, _payload):
            if "Opportunity Analyst" in system_prompt: return "qwen3:4b", analyst_json
            return "qwen3:4b", architect_json
        with patch.object(capability, "_llm_json", side_effect=fake_llm): result = capability.run_analyst(self.scenario)
        self.assertEqual(result["agent"], "AIMEC AI Opportunity Analyst")
        self.assertEqual(result["architect_handoff"]["agent"], "AIMEC AI Solution Architect")
        self.assertEqual(result["model"], "qwen3:4b")
        self.assertEqual(result["business_case"]["roi_after_operating_cost"]["annual_ai_cost"], 5596.56)
        self.assertLess(result["business_case"]["roi_after_operating_cost"]["annual_net_benefit"], result["business_case"]["initial_roi"]["annual_net_benefit"])


if __name__ == "__main__": unittest.main()
