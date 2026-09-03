// Paste into the demo page Console after selecting the synthetic invoice example.
// This creates two synthetic jobs. Re-pasting in the same tab reuses the same run.
window.aimecNativeCheck ??= (async () => {
  if (!['demo.aimec.io', 'localhost', '127.0.0.1'].includes(location.hostname)) {
    throw new Error('Run on the live demo or a local reproduction. Review the host guard for your own deployment.');
  }
  const call = async (name, input = {}) => {
    const api = document.modelContext;
    let raw;
    if (api?.getTools && api?.executeTool) {
      const tool = (await api.getTools()).find(t => t.name === name);
      if (!tool) throw new Error('Tool not registered: ' + name);
      raw = await api.executeTool(tool, JSON.stringify(input));
    } else {
      const testing = document.modelContextTesting ?? navigator.modelContextTesting;
      if (!testing?.executeTool) throw new Error('Native WebMCP testing unavailable');
      raw = await testing.executeTool(name, JSON.stringify(input));
    }
    const result = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!result || result.isError) throw new Error('Tool failed: ' + name);
    return result;
  };
  const scenario = JSON.parse(document.getElementById('scenario').value);
  const tools = await call('get_available_tools');
  const agents = await call('get_available_agents');
  if (!tools.tools?.some(t => t.id === 'aimec.business-diagnostics') ||
      !['aimec.ai-opportunity-analyst', 'aimec.ai-solution-architect'].every(
        id => agents.agents?.some(a => a.id === id))) throw new Error('Expected capabilities unavailable');
  const finish = async (label, job, architectExpected) => {
    window.aimecNativeCheckJobs ??= [];
    window.aimecNativeCheckJobs.push({label, job_id: job.job_id});
    console.log(label, job.job_id, 'submitted; waiting');
    const args = {job_id: job.job_id};
    const deadline = Date.now() + 8 * 60 * 1000;
    while (Date.now() < deadline) {
      const status = await call('get_task_status', args);
      if (['failed', 'interrupted', 'cancelled'].includes(status.state)) throw new Error(label + ': ' + status.state);
      if (status.state === 'completed') {
        const result = await call('get_task_result', args);
        const evidence = await call('get_execution_evidence', args);
        const check = {test: label, job_id: job.job_id, completed: true,
          result_present: !!result.result, digest_verified: evidence.result_digest_verified === true,
          provider_execution_count: evidence.provider_execution_count,
          architect_result_present: architectExpected ? !!result.result?.architect_handoff?.architecture : null};
        check.passed = check.result_present && check.digest_verified && check.provider_execution_count === 1 &&
          (!architectExpected || check.architect_result_present);
        return check;
      }
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    throw new Error(label + ' still pending; keep job ID and inspect status, do not blindly resubmit');
  };
  const checks = [];
  checks.push(await finish('ROI tool', await call('run_tool', {
    capability_id: 'aimec.business-diagnostics', operation_id: 'business.calculate_ai_roi',
    input: scenario.roi, request_id: crypto.randomUUID()
  }), false));
  checks.push(await finish('Analyst → Architect', await call('delegate_task', {
    capability_id: 'aimec.ai-opportunity-analyst', operation_id: 'business.analyze_opportunity',
    input: scenario, request_id: crypto.randomUUID()
  }), true));
  const summary = {passed: checks.every(c => c.passed), checks};
  console.log(JSON.stringify(summary, null, 2));
  return summary;
})();
