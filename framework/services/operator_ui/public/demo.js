"use strict";

(() => {
  const el = (id) => document.getElementById(id);
  const state = { tools: [], agents: [], job: null, poll: 0, view: 0, submitting: false, sessionReady: false };
  const request = async (url, body) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), body === undefined ? 30000 : 220000);
    try {
      const response = await fetch(url, { cache: "no-store", signal: controller.signal, headers: { "Content-Type": "application/json" }, ...(body === undefined ? {} : { method: "POST", body: JSON.stringify(body) }) });
      if (!response.ok) {
        let message = `Request rejected (${response.status}).`;
        try { const payload = await response.json(); if (payload.error) message += ` ${payload.error}`; } catch {}
        const error = new Error(message + " No automatic retry was attempted."); error.status = response.status; throw error;
      }
      return await response.json();
    } catch (error) {
      if (error.status) throw error;
      throw new Error(`Connection interrupted or timed out. ${body === undefined ? "" : "The job may still have run. "}No automatic retry was attempted.`);
    } finally { clearTimeout(timeout); }
  };
  const storage = (method, ...args) => { try { return sessionStorage[method](...args); } catch { return null; } };
  const nextView = () => { clearTimeout(state.poll); state.poll = 0; return ++state.view; };
  const text = (tag, content, className) => { const node = document.createElement(tag); node.textContent = content; if (className) node.className = className; return node; };
  const money = (value) => typeof value === "number" ? `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—";
  const controls = () => {
    const analyst = state.agents.some((a) => a.id === "aimec.ai-opportunity-analyst");
    const architect = state.agents.some((a) => a.id === "aimec.ai-solution-architect");
    el("run-flow").disabled = !state.sessionReady || state.submitting || !analyst;
    el("run-architect").disabled = !state.sessionReady || state.submitting || !architect;
    el("run-tool").disabled = !state.sessionReady || state.submitting || !state.tools.length || !el("tool-operation").value;
    el("tool-operation").disabled = !state.sessionReady || state.submitting || !state.tools.length;
  };

  const invoiceExample = () => ({
    business_problem: "Five accounts-payable employees spend about 20 hours each week processing supplier invoices. The ERP exposes an API, but internal process documentation is incomplete. Evaluate whether an AI-assisted invoice workflow is worth piloting and propose a safe implementation.",
    roi: { employees: 5, hours_per_week: 20, hourly_cost: 32, automation_percentage: 65, implementation_cost: 18000 },
    cost: { users: 8, requests_per_user_per_day: 75, tokens_per_request: 2600, cost_per_million_tokens: 0.35, monthly_infrastructure_cost: 450 },
    data_readiness: { crm_data_quality: 4, documentation_quality: 2, api_availability: 4, data_accuracy: 4, security_controls: 3, data_ownership: 3 },
    agentic_readiness: { api_access: 4, process_repeatability: 4, approval_points: 3, knowledge_documentation: 2, business_data_access: 4, automation_maturity: 3 },
    ai_readiness: { strategy_clarity: 3, data_quality_accessibility: 4, process_documentation: 2, tools_integrations: 4, security_privacy: 3, team_readiness: 3 }
  });
  const supportExample = () => ({
    business_problem: "Twelve support employees each spend about 15 hours per week answering repetitive tier-one customer questions. The company uses a helpdesk and CRM with APIs and has a large knowledge base, but approval rules for account changes are not fully documented. Evaluate a support copilot and controlled agent pilot.",
    roi: { employees: 12, hours_per_week: 15, hourly_cost: 28, automation_percentage: 55, implementation_cost: 24000 },
    cost: { users: 15, requests_per_user_per_day: 90, tokens_per_request: 3200, cost_per_million_tokens: 0.35, monthly_infrastructure_cost: 600 },
    data_readiness: { crm_data_quality: 4, documentation_quality: 4, api_availability: 4, data_accuracy: 3, security_controls: 3, data_ownership: 3 },
    agentic_readiness: { api_access: 4, process_repeatability: 4, approval_points: 2, knowledge_documentation: 4, business_data_access: 4, automation_maturity: 3 },
    ai_readiness: { strategy_clarity: 4, data_quality_accessibility: 4, process_documentation: 3, tools_integrations: 4, security_privacy: 3, team_readiness: 4 }
  });
  const fill = (value) => { el("scenario").value = JSON.stringify(value, null, 2); };
  const parseScenario = () => { try { const value = JSON.parse(el("scenario").value); if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(); return value; } catch { throw new Error("Enter a valid business-case JSON object. No job was submitted."); } };
  const metric = (label, value) => { const card = document.createElement("div"); card.className = "metric"; card.append(text("span", label), text("strong", value)); return card; };
  const agentCard = (label, title, body) => { const card = document.createElement("article"); card.className = "agent-card"; card.append(text("div", label, "agent-label"), text("h3", title), text("p", body || "")); return card; };

  const renderAnalyst = (result) => {
    const root = el("result"); root.replaceChildren(); const assessment = result.analyst_assessment || {}; const business = result.business_case || {}; const finalRoi = business.roi_after_operating_cost || {}; const cost = business.operating_cost || {};
    const metrics = document.createElement("div"); metrics.className = "result-grid"; metrics.append(metric("Recommendation", assessment.recommendation || "—"), metric("Net annual benefit", money(finalRoi.annual_net_benefit)), metric("Monthly AI cost", money(cost.monthly_total_cost))); root.append(metrics);
    const analyst = agentCard("Agent 01 · " + (result.model || "local model"), result.agent || "AIMEC AI Opportunity Analyst", assessment.rationale || ""); const chips = document.createElement("div"); chips.className = "chips"; for (const item of [assessment.priority, ...(assessment.risks || [])]) if (item) chips.append(text("span", item, "chip")); analyst.append(chips); root.append(analyst);
    const handoff = result.architect_handoff || {}; const architecture = handoff.architecture || {}; const architect = agentCard("Agent 02 · " + (handoff.model || "local model"), handoff.agent || "AIMEC AI Solution Architect", architecture.architecture_summary || ""); const components = document.createElement("div"); components.className = "chips"; for (const item of architecture.components || []) components.append(text("span", item, "chip")); architect.append(components); root.append(architect);
    root.append(text("h3", "Grounded tool trace")); const trace = document.createElement("ul"); trace.className = "trace"; for (const call of result.tool_calls || []) trace.append(text("li", `${call.tool}${call.stage ? ` · ${call.stage}` : ""}`)); for (const call of handoff.tool_calls || []) trace.append(text("li", `Architect · ${call.tool}`)); root.append(trace);
    const phases = architecture.phases || []; if (phases.length) { root.append(text("h3", "Pilot path")); const list = document.createElement("ul"); list.className = "trace"; for (const phase of phases) list.append(text("li", `${phase.phase}: ${phase.name} — ${phase.outcome}`)); root.append(list); }
  };
  const renderArchitect = (result) => {
    const root = el("result"); root.replaceChildren(); const architecture = result.architecture || {}; const cost = result.operating_cost || {}; const metrics = document.createElement("div"); metrics.className = "result-grid"; metrics.append(metric("Monthly cost", money(cost.monthly_total_cost)), metric("Annual cost", money(cost.annual_total_cost)), metric("Model", result.model || "—")); root.append(metrics);
    const card = agentCard("Agent 02", result.agent || "AIMEC AI Solution Architect", architecture.architecture_summary || ""); const chips = document.createElement("div"); chips.className = "chips"; for (const item of architecture.components || []) chips.append(text("span", item, "chip")); card.append(chips); root.append(card); root.append(text("h3", "Human approval points")); const approvals = document.createElement("ul"); approvals.className = "trace"; for (const item of architecture.human_approval_points || []) approvals.append(text("li", item)); root.append(approvals);
  };
  const renderTool = (result) => {
    const root = el("result"); root.replaceChildren();
    if (typeof result.score === "number") { const metrics = document.createElement("div"); metrics.className = "result-grid"; metrics.append(metric("Readiness score", `${result.score}/100`), metric("Band", result.band || "—"), metric("Priority gaps", String((result.priority_gaps || []).length))); root.append(metrics); const gaps = document.createElement("ul"); gaps.className = "trace"; for (const item of result.priority_gaps || []) gaps.append(text("li", item)); root.append(text("h3", "Priority gaps"), gaps); }
    else if (typeof result.annual_net_benefit === "number") { const metrics = document.createElement("div"); metrics.className = "result-grid"; metrics.append(metric("Gross annual savings", money(result.annual_gross_savings)), metric("Annual net benefit", money(result.annual_net_benefit)), metric("Payback", result.payback_months == null ? "Not calculated" : `${result.payback_months} mo`)); root.append(metrics); }
    else if (typeof result.monthly_total_cost === "number") { const metrics = document.createElement("div"); metrics.className = "result-grid"; metrics.append(metric("Monthly model cost", money(result.monthly_model_cost)), metric("Monthly total", money(result.monthly_total_cost)), metric("Annual total", money(result.annual_total_cost))); root.append(metrics); }
    else root.append(text("pre", JSON.stringify(result, null, 2)));
  };
  const showResult = (job) => { const result = job.result; if (!result) return; if (result.analyst_assessment) renderAnalyst(result); else if (result.architecture && result.operating_cost) renderArchitect(result); else renderTool(result); el("raw-result").textContent = JSON.stringify(job, null, 2); };

  const evidence = async (view = state.view) => { if (!state.job) return; const id = state.job; const run = await request(`/api/webmcp/tasks/${encodeURIComponent(id)}/evidence`); if (state.job !== id || state.view !== view) return; el("digest-status").textContent = run.result_digest_verified ? "Verified: provider output matches the saved artifact hash." : "Evidence is pending or could not be verified."; el("timeline").replaceChildren(...(run.events || []).map((event) => text("li", `${event.service} · ${event.event}${event.agent ? ` · ${event.agent}` : ""}${event.model ? ` · ${event.model}` : ""}`))); el("artifact-hash").textContent = run.artifacts?.[0] ? `SHA-256 ${run.artifacts[0].sha256}` : ""; return run; };
  const showJob = async (job, view) => {
    if (state.view !== view) return; if (!job || !/^WEBMCP-[a-f0-9]{32}$/.test(job.job_id || "")) throw new Error("Unexpected job response."); clearTimeout(state.poll); state.job = job.job_id; storage("setItem", "aimec-last-job", job.job_id); el("job-id").textContent = job.job_id; el("task-state").textContent = job.state; el("refresh-evidence").disabled = false; if (job.result) showResult(job);
    const id = job.job_id; const current = () => state.job === id && state.view === view;
    const refresh = async (attempt = 0) => { if (!current()) return; try { const status = await request(`/api/webmcp/tasks/${encodeURIComponent(id)}/status`); if (!current()) return; el("task-state").textContent = status.state; if (status.state === "completed") { const completed = await request(`/api/webmcp/tasks/${encodeURIComponent(id)}/result`); if (!current()) return; showResult(completed); await evidence(view); if (current()) el("message").textContent = "Execution complete. The business result and provider evidence are shown."; } else if (["failed", "interrupted"].includes(status.state)) { el("message").textContent = "Execution did not complete. Check that the local Ollama model is healthy; no automatic retry was attempted."; await evidence(view); } else if (attempt < 360) state.poll = setTimeout(() => refresh(attempt + 1), 500); else el("message").textContent = "Still running. Use the job ID with get_task_status; no replay was attempted."; } catch (error) { if (current()) el("message").textContent = error.message; } };
    await refresh();
  };
  const select = (job) => { const view = nextView(); void showJob(job, view).catch((error) => { if (state.view === view) el("message").textContent = error.message; }); };
  window.aimecAlphaUi = { showWebMcpExecution: (_label, job) => select(job), showCoordinatorJob: (job) => select(job) };

  const submit = async (capability, operationId, input, kind) => {
    if (!state.sessionReady || state.submitting) return; let view = state.view;
    try { state.submitting = true; controls(); view = nextView(); el("message").textContent = kind === "agent" ? "Local Qwen specialist is working through AIMEC…" : "Running approved AIMEC business diagnostic…"; const job = await request(kind === "agent" ? "/api/webmcp/tasks/delegate" : "/api/webmcp/tools/run", { capability_id: capability.id, operation_id: operationId, input, ...(typeof crypto.randomUUID === "function" ? { request_id: crypto.randomUUID() } : {}) }); await showJob(job, view); } catch (error) { if (state.view === view) el("message").textContent = error.message; } finally { state.submitting = false; controls(); }
  };
  const runAgent = (id) => { const scenario = parseScenario(); const agent = state.agents.find((item) => item.id === id); if (!agent) throw new Error("Requested agent is not currently approved and online."); let input = scenario; if (id === "aimec.ai-solution-architect") input = { business_problem: scenario.business_problem, cost: scenario.cost, data_readiness: scenario.data_readiness, agentic_readiness: scenario.agentic_readiness }; return submit(agent, agent.operations[0].id, input, "agent"); };
  const toolInput = (operationId, scenario) => ({ "business.calculate_ai_roi": scenario.roi, "business.estimate_ai_cost": scenario.cost, "business.assess_data_readiness": scenario.data_readiness, "business.assess_agentic_readiness": scenario.agentic_readiness, "business.assess_ai_readiness": scenario.ai_readiness })[operationId];

  el("invoice-example").addEventListener("click", () => fill(invoiceExample())); el("support-example").addEventListener("click", () => fill(supportExample()));
  el("run-flow").addEventListener("click", () => { try { void runAgent("aimec.ai-opportunity-analyst"); } catch (e) { el("message").textContent = e.message; } });
  el("run-architect").addEventListener("click", () => { try { void runAgent("aimec.ai-solution-architect"); } catch (e) { el("message").textContent = e.message; } });
  el("run-tool").addEventListener("click", () => { try { const scenario = parseScenario(); const tool = state.tools[0]; const operationId = el("tool-operation").value; const input = toolInput(operationId, scenario); if (!tool || !input) throw new Error("The selected business diagnostic is unavailable."); void submit(tool, operationId, input, "tool"); } catch (e) { el("message").textContent = e.message; } });
  el("refresh-evidence").addEventListener("click", () => { const view = state.view; void evidence(view).catch((error) => { if (state.view === view) el("message").textContent = error.message; }); });
  document.addEventListener("aimec-webmcp-ready", () => { el("webmcp-state").textContent = "WebMCP · 7 tools registered"; });
  el("webmcp-state").textContent = document.modelContext?.registerTool ? "Registering WebMCP tools…" : "WebMCP unavailable · UI works"; fill(invoiceExample()); const startupView = state.view; const previous = storage("getItem", "aimec-last-job"); const restoring = !!(previous && /^WEBMCP-[a-f0-9]{32}$/.test(previous)); window.aimecDemoSessionReady = request("/api/webmcp/config");
  void window.aimecDemoSessionReady.then((config) => { state.sessionReady = true; el("model-name").textContent = `${config.model || "Qwen"} via Ollama`; el("model-state").textContent = `Local model · ${config.model || "Qwen"}`; el("source-revision").textContent = config.source_commit === "unrecorded" ? "Local development revision" : `Source ${config.source_commit.slice(0, 12)}`; if (restoring) void request(`/api/webmcp/tasks/${previous}/status`).then((job) => showJob(job, startupView)).catch((error) => { if (state.view !== startupView) return; if (error.status === 404) storage("removeItem", "aimec-last-job"); el("message").textContent = "Could not restore the previous job. " + error.message; }); Promise.all([request("/api/webmcp/tools"), request("/api/webmcp/agents")]).then(([tools, agents]) => { state.tools = tools.tools || []; state.agents = agents.agents || []; const analyst = state.agents.find((item) => item.id === "aimec.ai-opportunity-analyst"); const architect = state.agents.find((item) => item.id === "aimec.ai-solution-architect"); el("analyst-name").textContent = analyst?.name || "Analyst unavailable"; el("architect-name").textContent = architect?.name || "Architect unavailable"; const tool = state.tools[0]; el("tool-name").textContent = tool ? `${tool.operations.length} AIMEC business diagnostics` : "Business diagnostics unavailable"; const picker = el("tool-operation"); picker.replaceChildren(); for (const operation of tool?.operations || []) { const option = document.createElement("option"); option.value = operation.id; option.textContent = operation.id.replace("business.", "").replaceAll("_", " "); picker.append(option); } controls(); if (!restoring && state.view === startupView) el("message").textContent = analyst && architect && tool ? "Ready. Run the full two-agent flow or call any AIMEC business diagnostic directly." : "Awaiting approved business capabilities or local-model service."; }).catch((error) => { if (!restoring && state.view === startupView) el("message").textContent = error.message; }); }).catch(() => { el("source-revision").textContent = "Source verification unavailable"; el("message").textContent = "Session initialization failed. Reload to try again; no job was submitted."; controls(); });
})();
