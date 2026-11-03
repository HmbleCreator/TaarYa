(function () {
  const fileInput = document.getElementById('report-file');
  const state = document.getElementById('report-state');
  const stateMessage = document.getElementById('report-state-message');
  const stateHelp = document.getElementById('report-state-help');
  const content = document.getElementById('report-content');

  function setState(message, kind) {
    state.hidden = false;
    state.dataset.state = kind || 'empty';
    stateMessage.textContent = message;
    stateHelp.hidden = state.dataset.state !== 'empty';
    content.hidden = true;
  }

  function cell(row, value, className) {
    const item = document.createElement('td');
    item.textContent = value;
    if (className) item.className = className;
    row.appendChild(item);
  }

  function formatInterval(interval, suffix) {
    if (!interval || interval.mean == null) return 'Not reported';
    const mean = Number(interval.mean);
    const low = Number(interval.lower_95);
    const high = Number(interval.upper_95);
    if (![mean, low, high].every(Number.isFinite)) return 'Not reported';
    return `${mean.toFixed(3)} [${low.toFixed(3)}, ${high.toFixed(3)}]${suffix || ''}`;
  }

  function validate(report) {
    if (!report || typeof report !== 'object' || Array.isArray(report)) throw new Error('Report must be a JSON object.');
    if (!report.study_id || !report.dataset || !report.systems || typeof report.systems !== 'object') {
      throw new Error('The selected file is not a TaarYa study report.');
    }
    for (const [name, system] of Object.entries(report.systems)) {
      if (!system.metrics || !Number.isInteger(system.n_scenarios)) {
        throw new Error(`The report has an invalid results record for ${name}.`);
      }
    }
    if (!Array.isArray(report.paired_comparisons)) throw new Error('The report has no paired comparison results.');
  }

  function showReport(report) {
    validate(report);
    const meta = document.getElementById('report-meta');
    const systemRows = document.getElementById('system-rows');
    const pairedRows = document.getElementById('paired-rows');
    meta.replaceChildren();
    systemRows.replaceChildren();
    pairedRows.replaceChildren();

    const metadata = [
      ['Study', report.study_id],
      ['Protocol', report.protocol_version || 'Not recorded'],
      ['Dataset', `${report.dataset.dataset_id || 'Unknown'} / ${report.dataset.release || 'Unknown'}`],
      ['Scenarios', String(report.scenario_count ?? 'Not reported')],
      ['Participants', String(report.participant_count ?? 'Not reported')],
      ['Uncertainty unit', report.bootstrap_unit || 'Not reported'],
      ['Cutoff', `k=${report.k ?? 'Not reported'}`],
    ];
    metadata.forEach(([name, value]) => {
      const item = document.createElement('span');
      const key = document.createElement('strong');
      key.textContent = `${name}: `;
      item.append(key, document.createTextNode(value));
      meta.appendChild(item);
    });

    for (const [name, system] of Object.entries(report.systems)) {
      const row = document.createElement('tr');
      cell(row, name);
      cell(row, String(system.n_scenarios), 'report-number');
      cell(row, String(system.n_participants ?? 'Not reported'), 'report-number');
      cell(row, formatInterval(system.metrics.precision_at_k));
      cell(row, formatInterval(system.metrics.recall_at_k));
      cell(row, formatInterval(system.metrics.ndcg_at_k));
      cell(row, formatInterval(system.metrics.provenance_completeness));
      cell(row, formatInterval(system.metrics.task_time_s, ' s'));
      cell(row, formatInterval(system.metrics.tool_latency_s, ' s'));
      cell(row, formatInterval(system.metrics.dataset_match));
      systemRows.appendChild(row);
    }

    for (const comparison of report.paired_comparisons) {
      const row = document.createElement('tr');
      cell(row, `${comparison.left_system} minus ${comparison.right_system}`);
      cell(row, String(comparison.paired_scenarios), 'report-number');
      cell(row, String(comparison.paired_participants ?? 'Not reported'), 'report-number');
      for (const metric of ['precision_at_k', 'recall_at_k', 'ndcg_at_k', 'provenance_completeness', 'task_time_s', 'tool_latency_s']) {
        cell(row, formatInterval(comparison.left_minus_right?.[metric]));
      }
      pairedRows.appendChild(row);
    }

    document.getElementById('report-note').textContent = report.interpretation_note ||
      'Interpret results only for the scenarios and data release recorded in this report.';
    state.hidden = true;
    content.hidden = false;
  }

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    setState('Reading report…', 'loading');
    try {
      showReport(JSON.parse(await file.text()));
    } catch (error) {
      setState(error.message || 'Could not read this report.', 'error');
    }
  });
})();
