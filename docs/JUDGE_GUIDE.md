# Judge walkthrough

Live URL: https://demo.aimec.io

Use public/synthetic inputs only. No account is required for the demo. Sessions own
their results, so stay in the same browser tab while retrieving a job's evidence.

## Human workflow

1. Select **Invoice automation**.
2. Review the example assumptions and choose **Run Analyst → Architect** once.
3. Allow the CPU-hosted model to finish. Inspect both specialist sections, the cost
   and ROI calculations, the proposed pilot phases and the execution evidence.
4. Modify an assumption or select the support scenario to compare another case.

This is an assessment and proposed implementation, not a live invoice-processing
integration. Financial figures are assumptions-based estimates, not guaranteed savings.

## Native WebMCP execution check

1. Use a WebMCP-capable browser. For supported Chrome builds, enable
   `chrome://flags/#enable-webmcp-testing` and relaunch.
2. Open the live URL or your local demo. Confirm **WebMCP · 7 tools registered**.
3. Select the supplied invoice example; do not press a Run button.
4. Open Chrome DevTools Console and paste the contents of [webmcp-check.js](webmcp-check.js).
5. Keep the page open. The check discovers capabilities, executes an ROI tool job,
   delegates the business case, polls existing job IDs, then retrieves results and evidence.

Expected final summary: `passed: true`, result presence and verified digests for
both jobs, one provider execution per top-level job, and an Architect result for
the delegated case. A timeout means the check has not established completion;
it does not mean the backend job was cancelled. Do not submit another job blindly.

This checks all seven native interfaces. It manually invokes registered tools; it
does not demonstrate an external browser AI autonomously choosing those tools.

## Optional browser-agent walkthrough

In a compatible agent-enabled browser, ask the agent to inspect the registered
tools, discover the business specialists, submit the synthetic case using the
published input schema, wait for completion, then retrieve the result and evidence.
The host agent must have access to this page and its WebMCP capabilities. This
repository does not include or claim a tested general-purpose browser-agent client.

## Useful evidence

- The result includes both specialist roles and the final recalculated ROI.
- The UI and WebMCP expose the same session-owned job.
- The execution ledger reports the provider and result digest.
- One top-level provider execution is expected; the internal Architect call is
  not recorded as an independently scheduled downstream A2A job.

Do not publish browser cookies, authentication headers, HAR files, runtime databases
or logs containing user inputs. Sanitized pass/fail summaries are sufficient.
