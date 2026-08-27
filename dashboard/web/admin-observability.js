(() => {
  const $ = (id) => document.getElementById(id);
  const text = (value) => value === null || value === undefined || value === '' ? '—' : String(value);
  const escapeHtml = (value) => text(value).replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));

  function query() {
    const params = new URLSearchParams();
    [['agent_id','agent-filter'],['customer_id','customer-filter'],['instance_id','instance-filter'],['region_id','region-filter']].forEach(([key,id]) => {
      const value = $(id).value.trim();
      if (value) params.set(key, value);
    });
    return params.toString();
  }

  function card(label, value, detail='') {
    return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`;
  }

  function renderRows(target, rows, fields) {
    target.innerHTML = rows.length ? rows.map((row) => `<tr>${fields.map((field) => `<td>${escapeHtml(typeof field === 'function' ? field(row) : row[field])}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${fields.length}" class="empty">Nenhum registro.</td></tr>`;
  }

  async function load() {
    $('health-text').textContent = 'Atualizando visão consolidada…';
    const suffix = query();
    const response = await fetch(`/api/admin/observability${suffix ? `?${suffix}` : ''}`, {headers:{'Accept':'application/json'}});
    if (!response.ok) {
      $('health-text').textContent = `Falha ao carregar observabilidade (${response.status}).`;
      return;
    }
    const data = await response.json();
    const s = data.summary || {};
    const alerts = s.alerts || {};
    const queues = s.queues || {};
    $('health-text').textContent = `Saúde global: ${text(data.health).toUpperCase()}`;
    $('summary').innerHTML = [
      card('Agents', s.agents?.total ?? 0, JSON.stringify(s.agents?.by_status || {})),
      card('Instâncias', s.instances?.total ?? 0, JSON.stringify(s.instances?.by_status || {})),
      card('Operações recentes', s.operations?.total_recent ?? 0, JSON.stringify(s.operations?.by_status || {})),
      card('Alertas ativos', alerts.active ?? 0, `${alerts.critical ?? 0} critical · ${alerts.warning ?? 0} warning`),
      card('Clientes com problema', alerts.customer_problems ?? 0, 'incidentes funcionais ativos'),
      card('Filas', queues.metrics ?? 0, `${queues.potentially_stuck ?? 0} sinais potencialmente travados`),
    ].join('');

    renderRows($('operations'), data.recent?.operations || [], ['operation_type','status','agent_id','instance_id','correlation_id']);
    renderRows($('alerts'), data.recent?.alerts || [], ['severity','code','scope','status','correlation_id']);
    renderRows($('activity'), data.recent?.activity || [], ['actor','role','action',(row) => `${text(row.target_type)}:${text(row.target_id)}`,'correlation_id']);
  }

  $('refresh').addEventListener('click', load);
  $('apply').addEventListener('click', load);
  load().catch((error) => { $('health-text').textContent = `Falha: ${error.message}`; });
  setInterval(() => load().catch(() => {}), 30000);
})();
