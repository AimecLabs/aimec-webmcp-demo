"""AIMEC business diagnostics and two tool-grounded local-LLM specialists."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from aimec_capability_registry import _reject_secret_material, _validate_payload


_manifest_override = os.getenv("AIMEC_BUSINESS_MANIFEST_DIR")
MANIFEST_DIR = (
    Path(_manifest_override) if _manifest_override is not None else
    (Path("/app/manifests") if Path("/app/manifests").exists()
     else Path(__file__).resolve().parents[2] / "registry/capabilities")
)
MANIFESTS = {
    manifest["identity"]["id"]: manifest
    for manifest in (
        json.loads((MANIFEST_DIR / "business-diagnostics.tool.json").read_text(encoding="utf-8")),
        json.loads((MANIFEST_DIR / "ai-opportunity-analyst.agent.json").read_text(encoding="utf-8")),
        json.loads((MANIFEST_DIR / "ai-solution-architect.agent.json").read_text(encoding="utf-8")),
    )
}
OPERATIONS = {
    operation["id"]: (manifest, operation)
    for manifest in MANIFESTS.values()
    for operation in manifest["operations"]
}
DIRECTIONAL_NOTICE = (
    "Directional planning estimate only. Validate assumptions, integration constraints, "
    "security requirements and commercial quotes before making an investment decision."
)
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")


DATA_DIMENSIONS = {
    "crm_data_quality": "CRM/customer data quality",
    "documentation_quality": "Internal documentation quality",
    "api_availability": "API/integration availability",
    "data_accuracy": "Overall data accuracy",
    "security_controls": "Security/access controls",
    "data_ownership": "Clear data ownership",
}
AGENTIC_DIMENSIONS = {
    "api_access": "Systems expose APIs agents can use",
    "process_repeatability": "Processes are documented and repeatable",
    "approval_points": "Human approval points are clearly defined",
    "knowledge_documentation": "Company knowledge is documented",
    "business_data_access": "Agents can access useful business data",
    "automation_maturity": "Existing automation maturity",
}
AI_DIMENSIONS = {
    "strategy_clarity": "AI strategy clarity",
    "data_quality_accessibility": "Data quality/accessibility",
    "process_documentation": "Process documentation",
    "tools_integrations": "Existing tools/integrations",
    "security_privacy": "Security/privacy readiness",
    "team_readiness": "Team readiness",
}


def _finite_number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return number


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return value


def _money(value: float) -> float:
    return round(float(value), 2)


def calculate_ai_roi(arguments: dict[str, Any]) -> dict[str, Any]:
    employees = _integer(arguments["employees"], "employees", 1, 100_000)
    hours = _finite_number(arguments["hours_per_week"], "hours_per_week", 0, 168)
    hourly_cost = _finite_number(arguments["hourly_cost"], "hourly_cost", 0, 10_000)
    automation = _finite_number(arguments["automation_percentage"], "automation_percentage", 0, 100)
    monthly_ai_cost = _finite_number(arguments.get("monthly_ai_cost", 0), "monthly_ai_cost", 0, 100_000_000)
    implementation_cost = _finite_number(arguments.get("implementation_cost", 0), "implementation_cost", 0, 1_000_000_000)

    annual_labor_cost = employees * hours * hourly_cost * 52
    annual_gross_savings = annual_labor_cost * automation / 100
    annual_ai_cost = monthly_ai_cost * 12
    annual_net_benefit = annual_gross_savings - annual_ai_cost
    monthly_net_benefit = annual_net_benefit / 12
    payback = None
    if implementation_cost > 0 and monthly_net_benefit > 0:
        payback = round(implementation_cost / monthly_net_benefit, 1)

    return {
        "annual_labor_cost": _money(annual_labor_cost),
        "annual_gross_savings": _money(annual_gross_savings),
        "annual_ai_cost": _money(annual_ai_cost),
        "annual_net_benefit": _money(annual_net_benefit),
        "monthly_net_benefit": _money(monthly_net_benefit),
        "payback_months": payback,
        "directional_notice": DIRECTIONAL_NOTICE,
    }


def estimate_ai_cost(arguments: dict[str, Any]) -> dict[str, Any]:
    users = _integer(arguments["users"], "users", 1, 1_000_000)
    requests = _finite_number(arguments["requests_per_user_per_day"], "requests_per_user_per_day", 0, 100_000)
    tokens = _integer(arguments["tokens_per_request"], "tokens_per_request", 1, 10_000_000)
    token_cost = _finite_number(arguments["cost_per_million_tokens"], "cost_per_million_tokens", 0, 100_000)
    infrastructure = _finite_number(arguments["monthly_infrastructure_cost"], "monthly_infrastructure_cost", 0, 100_000_000)

    monthly_requests = users * requests * 30
    monthly_tokens = monthly_requests * tokens
    model_cost = monthly_tokens / 1_000_000 * token_cost
    monthly_total = model_cost + infrastructure
    return {
        "monthly_requests": round(monthly_requests, 2),
        "monthly_tokens": round(monthly_tokens, 2),
        "monthly_model_cost": _money(model_cost),
        "monthly_infrastructure_cost": _money(infrastructure),
        "monthly_total_cost": _money(monthly_total),
        "annual_total_cost": _money(monthly_total * 12),
        "directional_notice": DIRECTIONAL_NOTICE,
    }


def _readiness(arguments: dict[str, Any], dimensions: dict[str, str]) -> dict[str, Any]:
    values: dict[str, int] = {}
    for key in dimensions:
        values[key] = _integer(arguments[key], key, 1, 5)
    score = round(sum(values.values()) / (len(values) * 5) * 100)
    band = "ready" if score >= 75 else "developing" if score >= 50 else "foundation"
    gaps = [
        dimensions[key]
        for key, value in sorted(values.items(), key=lambda item: (item[1], item[0]))
        if value <= 2
    ]
    if not gaps:
        gaps = [
            dimensions[key]
            for key, _ in sorted(values.items(), key=lambda item: (item[1], item[0]))[:2]
        ]
    return {
        "score": score,
        "band": band,
        "priority_gaps": gaps[:6],
        "dimension_scores": values,
        "directional_notice": DIRECTIONAL_NOTICE,
    }


def assess_data_readiness(arguments: dict[str, Any]) -> dict[str, Any]:
    return _readiness(arguments, DATA_DIMENSIONS)


def assess_agentic_readiness(arguments: dict[str, Any]) -> dict[str, Any]:
    return _readiness(arguments, AGENTIC_DIMENSIONS)


def assess_ai_readiness(arguments: dict[str, Any]) -> dict[str, Any]:
    return _readiness(arguments, AI_DIMENSIONS)


TOOL_HANDLERS = {
    "business.calculate_ai_roi": calculate_ai_roi,
    "business.estimate_ai_cost": estimate_ai_cost,
    "business.assess_data_readiness": assess_data_readiness,
    "business.assess_agentic_readiness": assess_agentic_readiness,
    "business.assess_ai_readiness": assess_ai_readiness,
}


def _llm_settings() -> tuple[str, str]:
    base_url = os.getenv("AIMEC_LLM_BASE_URL", "http://ollama:11434").strip().rstrip("/")
    model = os.getenv("AIMEC_LLM_MODEL", "qwen3:4b").strip()
    parsed = urlsplit(base_url)
    if not base_url or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("local_llm_endpoint_invalid")
    local_name = parsed.hostname in {"localhost", "127.0.0.1", "::1"} or "." not in parsed.hostname
    if parsed.scheme != "https" and not local_name:
        raise RuntimeError("local_llm_endpoint_must_be_local_or_https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("local_llm_endpoint_invalid")
    if not MODEL_RE.fullmatch(model):
        raise RuntimeError("local_llm_model_invalid")
    return base_url, model


def _llm_json(system_prompt: str, user_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    base_url, model = _llm_settings()
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            },
        ],
        "options": {"temperature": 0.2, "num_predict": 1200},
    }
    request = Request(
        urljoin(base_url + "/", "api/chat"),
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=150) as response:
            raw = response.read(1_000_001)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("local_llm_unavailable") from exc
    if len(raw) > 1_000_000:
        raise RuntimeError("local_llm_response_too_large")
    try:
        envelope = json.loads(raw)
        content = envelope["message"]["content"]
        result = json.loads(content)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("local_llm_returned_invalid_json") from exc
    if not isinstance(result, dict):
        raise RuntimeError("local_llm_returned_invalid_json")
    return model, result


def _list_of_strings(value: Any, label: str, maximum: int = 6) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"{label}_invalid")
    output = []
    for item in value[:maximum]:
        text = str(item).strip()
        if not text or len(text) > 600:
            raise RuntimeError(f"{label}_invalid")
        output.append(text)
    return output


def _analyst_llm(problem: str, diagnostics: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    prompt = (
        "You are AIMEC AI Opportunity Analyst. Use only the supplied business problem and deterministic "
        "AIMEC diagnostic outputs. Return JSON only with keys opportunity, priority, rationale, risks, "
        "recommendation. priority must be HIGH, MEDIUM or LOW. recommendation must be PROCEED, PILOT or HOLD. "
        "Do not invent financial values, integrations, facts or guarantees. Keep rationale under 1200 characters "
        "and risks to at most five short strings."
    )
    model, raw = _llm_json(prompt, {"business_problem": problem, "diagnostics": diagnostics})
    opportunity = str(raw.get("opportunity") or "").strip()[:500]
    priority = str(raw.get("priority") or "").strip().upper()
    rationale = str(raw.get("rationale") or "").strip()[:1200]
    recommendation = str(raw.get("recommendation") or "").strip().upper()
    risks = _list_of_strings(raw.get("risks"), "analyst_risks", 5)
    if not opportunity or not rationale or priority not in {"HIGH", "MEDIUM", "LOW"} or recommendation not in {"PROCEED", "PILOT", "HOLD"}:
        raise RuntimeError("local_llm_analyst_output_invalid")
    return model, {
        "opportunity": opportunity,
        "priority": priority,
        "rationale": rationale,
        "risks": risks,
        "recommendation": recommendation,
    }


def _architect_llm(problem: str, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    prompt = (
        "You are AIMEC AI Solution Architect. Design a bounded pilot architecture from the supplied problem, "
        "readiness diagnostics and deterministic operating-cost estimate. Return JSON only with keys "
        "architecture_summary, components, human_approval_points, phases, implementation_notes. components and "
        "human_approval_points are arrays of short strings. phases is an array of objects with phase, name and outcome. "
        "Do not invent prices, savings, vendors already in use, compliance status, or deployment facts. Prefer local "
        "or private model execution when appropriate and make human approval explicit for consequential actions."
    )
    model, raw = _llm_json(prompt, {"business_problem": problem, **context})
    summary = str(raw.get("architecture_summary") or "").strip()[:1500]
    components = _list_of_strings(raw.get("components"), "architect_components", 8)
    approvals = _list_of_strings(raw.get("human_approval_points"), "architect_approvals", 8)
    notes = str(raw.get("implementation_notes") or "").strip()[:1500]
    phases_raw = raw.get("phases")
    if not isinstance(phases_raw, list):
        raise RuntimeError("architect_phases_invalid")
    phases = []
    for item in phases_raw[:5]:
        if not isinstance(item, dict):
            raise RuntimeError("architect_phases_invalid")
        phase = str(item.get("phase") or "").strip()[:80]
        name = str(item.get("name") or "").strip()[:160]
        outcome = str(item.get("outcome") or "").strip()[:500]
        if not phase or not name or not outcome:
            raise RuntimeError("architect_phases_invalid")
        phases.append({"phase": phase, "name": name, "outcome": outcome})
    if not summary or not components or not approvals or not phases:
        raise RuntimeError("local_llm_architect_output_invalid")
    return model, {
        "architecture_summary": summary,
        "components": components,
        "human_approval_points": approvals,
        "phases": phases,
        "implementation_notes": notes,
    }


def run_architect(arguments: dict[str, Any]) -> dict[str, Any]:
    problem = str(arguments["business_problem"]).strip()
    if not problem or len(problem) > 4000:
        raise ValueError("business_problem is invalid")
    cost = estimate_ai_cost(arguments["cost"])
    data = assess_data_readiness(arguments["data_readiness"])
    agentic = assess_agentic_readiness(arguments["agentic_readiness"])
    context = {
        "operating_cost": cost,
        "data_readiness": data,
        "agentic_readiness": agentic,
        "analyst_context": str(arguments.get("analyst_context") or "")[:4000],
    }
    model, architecture = _architect_llm(problem, context)
    return {
        "model": model,
        "agent": "AIMEC AI Solution Architect",
        "tool_calls": [
            {"tool": "business.estimate_ai_cost", "result": cost},
            {"tool": "business.assess_data_readiness", "result": data},
            {"tool": "business.assess_agentic_readiness", "result": agentic},
        ],
        "architecture": architecture,
        "operating_cost": cost,
        "directional_notice": DIRECTIONAL_NOTICE,
    }


def run_analyst(arguments: dict[str, Any]) -> dict[str, Any]:
    problem = str(arguments["business_problem"]).strip()
    if not problem or len(problem) > 4000:
        raise ValueError("business_problem is invalid")
    roi_initial = calculate_ai_roi(arguments["roi"])
    data = assess_data_readiness(arguments["data_readiness"])
    agentic = assess_agentic_readiness(arguments["agentic_readiness"])
    ai = assess_ai_readiness(arguments["ai_readiness"])
    diagnostics = {
        "initial_roi": roi_initial,
        "data_readiness": data,
        "agentic_readiness": agentic,
        "ai_readiness": ai,
    }
    model, assessment = _analyst_llm(problem, diagnostics)

    architect = run_architect({
        "business_problem": problem,
        "cost": arguments["cost"],
        "data_readiness": arguments["data_readiness"],
        "agentic_readiness": arguments["agentic_readiness"],
        "analyst_context": json.dumps(assessment, ensure_ascii=False, separators=(",", ":")),
    })
    final_roi_input = dict(arguments["roi"])
    final_roi_input["monthly_ai_cost"] = architect["operating_cost"]["monthly_total_cost"]
    roi_after_operating_cost = calculate_ai_roi(final_roi_input)

    return {
        "model": model,
        "agent": "AIMEC AI Opportunity Analyst",
        "tool_calls": [
            {"tool": "business.calculate_ai_roi", "stage": "initial", "result": roi_initial},
            {"tool": "business.assess_data_readiness", "result": data},
            {"tool": "business.assess_agentic_readiness", "result": agentic},
            {"tool": "business.assess_ai_readiness", "result": ai},
            {"tool": "business.calculate_ai_roi", "stage": "after_architect_cost", "result": roi_after_operating_cost},
        ],
        "analyst_assessment": assessment,
        "architect_handoff": architect,
        "business_case": {
            "initial_roi": roi_initial,
            "operating_cost": architect["operating_cost"],
            "roi_after_operating_cost": roi_after_operating_cost,
            "recommendation": assessment["recommendation"],
        },
        "directional_notice": DIRECTIONAL_NOTICE,
    }


AGENT_HANDLERS = {
    "business.analyze_opportunity": run_analyst,
    "business.design_solution": run_architect,
}


def _digest(result: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def execute_capability(handler: Any, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    _reject_secret_material(payload, "request")
    if payload.get("jsonrpc") == "2.0":
        if set(payload) - {"jsonrpc", "id", "method", "params", "_query"} or payload.get("method") != "tools/call":
            raise ValueError("unsupported MCP capability envelope")
        request_id = str(payload.get("id") or "")
        params = payload.get("params")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", request_id) or not isinstance(params, dict):
            raise ValueError("bounded MCP request id and params are required")
        if set(params) != {"name", "arguments"}:
            raise ValueError("unsupported MCP params")
        operation_id = str(params["name"])
        pair = OPERATIONS.get(operation_id)
        if pair is None or pair[0]["kind"] != "tool" or operation_id not in TOOL_HANDLERS:
            raise ValueError("unsupported business tool operation")
        arguments = params["arguments"]
        _validate_payload(arguments, pair[1]["input_schema"], "input")
        result = TOOL_HANDLERS[operation_id](arguments)
        _validate_payload(result, pair[1]["output_schema"], "output")
        correlation = handler.headers.get("X-AIMEC-Correlation-ID", request_id)
        handler.state.logger.emit(
            "business_tool_completed",
            run_id=correlation,
            operation_id=operation_id,
            result_sha256=_digest(result),
            output_fields=sorted(result),
        )
        return 200, {"jsonrpc": "2.0", "id": request_id, "result": result}

    if set(payload) - {"taskId", "correlationId", "operation", "input", "_query"}:
        raise ValueError("unsupported A2A capability envelope")
    task_id = str(payload.get("taskId") or "")
    correlation = str(payload.get("correlationId") or "")
    operation_id = str(payload.get("operation") or "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", task_id) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", correlation):
        raise ValueError("bounded A2A task and correlation ids are required")
    if handler.headers.get("Idempotency-Key") != task_id or handler.headers.get("X-AIMEC-Correlation-ID") != correlation:
        raise ValueError("A2A correlation headers do not match")
    pair = OPERATIONS.get(operation_id)
    if pair is None or pair[0]["kind"] != "agent" or operation_id not in AGENT_HANDLERS:
        raise ValueError("unsupported business agent operation")
    arguments = payload.get("input")
    _validate_payload(arguments, pair[1]["input_schema"], "input")
    result = AGENT_HANDLERS[operation_id](arguments)
    _validate_payload(result, pair[1]["output_schema"], "output")
    handler.state.logger.emit(
        "business_agent_completed",
        run_id=correlation,
        task_id=task_id,
        operation_id=operation_id,
        agent=result["agent"],
        model=result["model"],
        result_sha256=_digest(result),
        output_fields=sorted(result),
    )
    return 200, {"taskId": task_id, "state": "completed", "result": result}
