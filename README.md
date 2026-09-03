# AIMEC Alpha — WebMCP Business-Agent Demo

[Live demo](https://demo.aimec.io) · [MIT license](LICENSE) · [Judge walkthrough](docs/JUDGE_GUIDE.md) · [What is new](PROVENANCE.md)

Turn a synthetic business automation opportunity into a structured assessment:
deterministic ROI and readiness diagnostics, a local-model opportunity analysis,
a proposed implementation architecture, and ROI recalculated with estimated operating costs.

The same workflow is available to a person through the UI and to a browser agent
through seven registered WebMCP tools. Results remain linked to a session-owned job
and execution evidence, so users can inspect what ran and what it returned.

This is a runnable, deliberately narrow demo export. It is **not the full private
AIMEC platform** and does not require access to that platform or its Git history.

## What you can try

1. Open the live demo and select **Invoice automation**.
2. Review the synthetic assumptions: staffing, time spent, automation percentage,
   operating costs and readiness scores.
3. Select **Run Analyst → Architect** once. The first CPU inference may take several minutes.
4. Inspect the recommendation, proposed architecture, operating-cost calculation,
   net annual benefit, tool trace and execution evidence.
5. Change a stated assumption to explore a different business case.

The **Support automation** preset offers a second synthetic scenario. The Architect
and each business diagnostic can also be invoked independently.

### Five deterministic operations

| Operation | Output |
| --- | --- |
| `business.calculate_ai_roi` | Labor costs, potential savings, net benefit and payback |
| `business.estimate_ai_cost` | Token-volume and infrastructure cost estimates |
| `business.assess_data_readiness` | Readiness score and priority gaps |
| `business.assess_agentic_readiness` | Process/integration readiness score and gaps |
| `business.assess_ai_readiness` | Overall readiness score and gaps |

### Two complementary specialists

- **AI Opportunity Analyst:** runs diagnostics, asks Qwen to synthesize the opportunity,
  invokes the Architect, then recalculates ROI using the estimated operating cost.
- **AI Solution Architect:** uses cost/readiness diagnostics and Qwen to propose
  components, pilot phases and human approval points.

Both roles share one local Ollama server and the `qwen3:1.7b` model. They are distinct
role prompts and output contracts, not two separately hosted model instances.
The workflow order and diagnostic calls are programmed, not autonomously selected by an LLM.

## Why WebMCP

A browser agent can discover typed capabilities, submit a structured business case,
and retrieve status, results and evidence without scraping the UI or simulating clicks.
People can inspect the corresponding result in the same page. The useful boundary is
structured, inspectable execution—not a claim that an LLM cannot calculate ROI itself.

`framework/services/operator_ui/public/webmcp.js` registers these tools with
`document.modelContext.registerTool`:

| Interface | Purpose |
| --- | --- |
| `get_available_tools` | Discover approved business operations and their input schemas |
| `run_tool` | Execute one approved diagnostic |
| `get_available_agents` | Discover the two approved specialists |
| `delegate_task` | Submit a structured case and receive a durable job ID |
| `get_task_status` | Read the job state |
| `get_task_result` | Retrieve the structured result and artifact references |
| `get_execution_evidence` | Retrieve provider events and result-digest checks |

For native WebMCP, use a compatible browser. In supported Chrome builds enable
`chrome://flags/#enable-webmcp-testing` and relaunch. The page should report
**WebMCP · 7 tools registered**. See the [Chrome documentation](https://developer.chrome.com/docs/ai/webmcp).
The normal UI remains usable when native WebMCP is unavailable.

## Run locally

Requirements: Docker Engine with the Compose plugin; internet access for initial
container/model downloads; a CPU-capable machine with approximately 8 GB RAM and
adequate disk space for container images plus model weights. No paid model API key is needed.

```bash
git clone https://github.com/AimecLabs/aimec-webmcp-demo.git
cd aimec-webmcp-demo
bash scripts/demo.sh start
```

Open [http://localhost:8020](http://localhost:8020). The port is bound to loopback;
the model server and capability registry are not exposed to your network.
The first start downloads Qwen. A startup health check verifies model availability,
not successful inference: run a scenario to test the actual workflow.

```bash
bash scripts/demo.sh status
bash scripts/demo.sh logs
bash scripts/demo.sh stop
```

Stopping preserves model, job and execution-event volumes. Do not use `down -v`
unless you intentionally want to erase that data. Local launch uses a separate
Compose project, `aimec-webmcp-public`.

Defaults: `qwen3:1.7b`, 4 GB model memory limit and 2 CPUs. To override, prefix the
command, for example `AIMEC_OLLAMA_MEMORY=6g bash scripts/demo.sh start`.
Keep the same settings on later starts. The live-tested CPU build disables Qwen
thinking and caps generated output; this adjustment is explicit in the advisory Dockerfile.

Container tags/model tags can change upstream. This export pins the application
source provenance, not every downloaded image or model digest. Record those digests
for a fully frozen runtime deployment.

## Tests

Python 3.12+ is sufficient for the included offline tests; the application uses
the Python standard library. Node.js is needed only for JavaScript syntax checks.

```bash
python3 -m unittest discover -s framework/tests -p 'test_*.py' -v
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --check framework/services/operator_ui/public/demo.js
node --check framework/services/operator_ui/public/webmcp.js
```

The unit tests use explicitly mocked model responses. They do not prove model
quality, CPU performance or a real Ollama round trip. For live native browser
testing, follow [the judge guide](docs/JUDGE_GUIDE.md).

On September 3, 2026 the owner reported a successful hosted UI workflow and supplied
a Chrome native-WebMCP check showing completed ROI and Analyst→Architect jobs,
saved results, verified digests, one provider execution per top-level job, and an
Architect result. This is owner-supplied acceptance evidence, not a new independent
Docker/inference run of this public export. See [PROVENANCE.md](PROVENANCE.md).

## Architecture and boundaries

The browser calls a restricted Alpha HTTP surface. Alpha validates requests,
looks up approved capabilities in the registry, records durable job state in SQLite,
and calls the business advisory service. That service performs calculations and
local Ollama inference. A separate SQLite event ledger supports digest comparison.

Top-level tool execution uses MCP-style `tools/call` JSON-RPC messages; specialist
delegation uses the project's bounded A2A-style envelope. This is not a claim of
complete MCP/A2A protocol conformance. The Analyst-to-Architect handoff is a function
call within the advisory service, not another independently scheduled remote agent job.
Evidence proves top-level provider execution and saved-result integrity; it is not
cryptographic proof of every reasoning step or financial correctness.

## Safety and limitations

- Only public or synthetic inputs. Local inference means local to the **server**,
  not inference inside the visitor's browser.
- Session-scoped results are not a full tenant authentication/authorization system.
- Calculations depend on user-supplied assumptions; readiness scoring is heuristic.
- Model output can be incomplete or wrong. Review before making business decisions.
- This demo proposes a pilot; it does not process invoices, connect to an ERP,
  transfer money, or deploy an implementation.
- Approval recommendations in generated plans are not live approval workflows.
- Do not expose Ollama or registry ports. Public deployment requires HTTPS,
  secure cookies, origin validation and verified build identity. See [deployment notes](docs/DEPLOYMENT.md).
- This repository is not a production security audit or a general-purpose autonomous agent platform.

## License

AIMEC-authored code and documentation in this export are licensed under **MIT**.
This permits commercial reuse subject to the license notice and warranty disclaimer.
It does not license the rest of the private AIMEC platform or grant rights to AIMEC trademarks.

Qwen model weights and downloaded runtime components retain their own licenses.
Weights, container images, credentials, databases and Git history are not included.
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
