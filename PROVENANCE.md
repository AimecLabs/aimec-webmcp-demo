# Demo scope, source provenance and acceptance

## Prior work versus challenge work

AIMEC's private platform and business-tool concepts existed before this export.
The shared HTTP helpers, capability registry, durable task store and policy contracts
are reused building blocks. They must not be presented as all newly invented for this challenge.

The challenge-specific work exposes selected capabilities through a live WebMCP
browser interface, session-owned execution/results/evidence, and a runnable public
demo. On September 3, 2026 the business-agent extension added five business
diagnostics, the Opportunity Analyst and Solution Architect roles, local Qwen
inference and an updated UI in place of the earlier bounded SEO example.

The export baseline is upstream commit
`fc425bcbb146a4186ebf26edf7e96d80acd5fa21`, dated
`2026-09-03T13:29:33Z`, titled “BC-094: harden local Qwen runtime for CPU demo”.
The upstream repository is private; its history is deliberately not included.
`EXPORT_MANIFEST.json` records upstream Git blob IDs and SHA-256 values for retained
files so source correspondence can be inspected without importing private history.
Capability manifests retain their historical upstream provenance identifiers;
those private URLs are metadata, not dependencies or required downloads.

## Public-export changes

The Python business logic, browser code, shared runtime modules, capability
manifests and CPU inference Dockerfile come from that pinned baseline.
Packaging changes are limited to:

- remove the old SEO-specific browser verification script and its unused Docker COPY;
- default the UI port to loopback and model resources to 4 GB/2 CPUs, matching the tested VPS configuration;
- fail model initialization if the model download fails;
- add MIT licensing, dependency notices, this README/docs, local startup helper,
  generic HTTPS preparation, native WebMCP check and packaging tests.

The public export is therefore not byte-for-byte identical to the hosted source
directory. It preserves application behavior while making the demo independently
runnable. It does not include the VPS cutover script, server addresses, SSH keys,
certificates, sessions, logs, databases, model weights or private platform history.

## Acceptance evidence and its limits

Owner-supplied evidence on September 3, 2026 showed:

- a successful hosted business-agent UI run;
- seven registered native WebMCP interfaces;
- native discovery, direct ROI tool execution and Analyst delegation;
- completed task status, saved results and verified result digests;
- one provider execution for each top-level test job;
- an Architect architecture result inside the Analyst result.

These are owner-performed live tests, reported through screenshots/console output.
The export's offline tests use mock LLM responses and must not be described as fresh
live-model acceptance. The old SEO demo's restart acceptance does not automatically
establish restart acceptance for these new business agents.

The native tool check manually invokes browser-registered WebMCP tools. An external
browser AI independently deciding which tools to use is a separate evaluation.
The programmatic Analyst→Architect handoff runs within one advisory service.

## Reproduction

Use the public README's local startup instructions and judge guide. For strict
reproducibility, record the image digests and Ollama model digest on the machine
where you run the demo; tags alone are not immutable.
