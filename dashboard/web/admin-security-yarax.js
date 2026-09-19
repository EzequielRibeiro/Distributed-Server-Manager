(() => {
  const $ = (id) => document.getElementById(id);
  const controllerHeaders = (extra = {}) => ({'Accept':'application/json','X-Capivara-Auth-Area':'controller',...extra});
  const requestOptions = (extra = {}) => ({credentials:'same-origin',cache:'no-store',...extra});
  const text = (value) => value === null || value === undefined || value === '' ? '—' : String(value);
  const escapeHtml = (value) => text(value).replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));

  function badge(value) {
    const token = text(value).toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
    return `<span class="badge badge-${escapeHtml(token)}">${escapeHtml(value)}</span>`;
  }

  function query() {
    const params = new URLSearchParams();
    const agent = $('agent-filter').value.trim();
    const instance = $('instance-filter').value.trim();
    const result = $('result-filter').value.trim();
    if (agent) params.set('agent_id', agent);
    if (instance) params.set('instance_id', instance);
    if (result) params.set('result', result);
    params.set('limit', '200');
    return params.toString();
  }

  function card(label, value, detail='') {
    return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`;
  }

  function renderAgents(rows) {
    $('agents').innerHTML = rows.length ? rows.map((row) => `<tr>
      <td><strong>${escapeHtml(row.name || row.agent_id)}</strong><small>${escapeHtml(row.agent_id)}</small></td>
      <td>${badge(row.health_status || 'offline')}</td>
      <td>${badge(row.state || 'unknown')}</td>
      <td>${escapeHtml(row.engine_version)}${row.engine_managed ? '<small>managed</small>' : ''}</td>
      <td>${escapeHtml(row.ruleset_version)}${row.rules_managed ? '<small>managed</small>' : ''}</td>
      <td>${escapeHtml(row.rules_count)}</td>
      <td>${badge(row.ruleset_checksum_valid === true ? 'valid' : row.ruleset_checksum_valid === false ? 'invalid' : 'unknown')}</td>
      <td class="error-cell">${escapeHtml(row.last_error)}</td>
      <td class="operation-buttons">
        <button type="button" data-yarax-action="install_engine" data-agent-id="${escapeHtml(row.agent_id)}">Engine</button>
        <button type="button" data-yarax-action="install_rules" data-agent-id="${escapeHtml(row.agent_id)}">Regras</button>
        <button type="button" data-yarax-action="test_scan" data-agent-id="${escapeHtml(row.agent_id)}">Teste</button>
        <button type="button" data-yarax-action="rollback_rules" data-agent-id="${escapeHtml(row.agent_id)}">Rollback</button>
      </td>
    </tr>`).join('') : '<tr><td colspan="8" class="empty">Nenhum Agent encontrado.</td></tr>';
  }

  function renderEvents(rows) {
    $('events').innerHTML = rows.length ? rows.map((row) => `<tr>
      <td>${escapeHtml(row.occurred_at)}</td>
      <td>${escapeHtml(row.agent_id)}</td>
      <td>${escapeHtml(row.instance_id)}</td>
      <td><strong>${escapeHtml(row.content_id)}</strong><small>${escapeHtml(row.provider || row.game_id)}</small></td>
      <td>${badge(row.result || row.event_type)}</td>
      <td>${row.duration_ms === null || row.duration_ms === undefined ? '—' : escapeHtml(row.duration_ms + ' ms')}</td>
      <td>${escapeHtml(row.match_count || 0)}</td>
      <td class="error-cell">${escapeHtml(row.error)}
        ${row.agent_id && row.instance_id && row.content_id ? `<button type="button" class="rescan" data-yarax-action="rescan_content" data-agent-id="${escapeHtml(row.agent_id)}" data-instance-id="${escapeHtml(row.instance_id)}" data-content-id="${escapeHtml(row.content_id)}">Re-scan</button>` : ''}
      </td>
    </tr>`).join('') : '<tr><td colspan="8" class="empty">Nenhum evento YARA-X encontrado.</td></tr>';
  }

  async function runOperation(button) {
    const payload = {
      action: button.dataset.yaraxAction,
      agent_id: button.dataset.agentId,
    };
    if (button.dataset.instanceId) payload.instance_id = button.dataset.instanceId;
    if (button.dataset.contentId) payload.content_id = button.dataset.contentId;
    button.disabled = true;
    try {
      const response = await fetch('/api/admin/security/yara-x/operations', {
        method: 'POST',
        headers: controllerHeaders({'Content-Type':'application/json'}),
        credentials: 'same-origin',
        cache: 'no-store',
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.message || body.error || `HTTP ${response.status}`);
      $('status-text').textContent = `Operação ${payload.action} agendada: ${body.operation_id}`;
      await loadOperations();
    } catch (error) {
      $('status-text').textContent = `Falha na operação: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  }

  async function loadOperations() {
    const agent = $('agent-filter').value.trim();
    const params = new URLSearchParams({limit:'100'});
    if (agent) params.set('agent_id', agent);
    const response = await fetch(`/api/admin/security/yara-x/operations?${params}`, requestOptions({headers:controllerHeaders()}));
    if (!response.ok) return;
    const data = await response.json();
    const rows = data.operations || [];
    $('operations').innerHTML = rows.length ? rows.map((row) => `<tr>
      <td>${escapeHtml(row.created_at)}</td>
      <td>${escapeHtml(row.agent_id)}</td>
      <td>${escapeHtml(row.action)}</td>
      <td>${badge(row.status)}</td>
      <td>${escapeHtml([row.instance_id,row.content_id].filter(Boolean).join(' / '))}</td>
      <td class="error-cell">${escapeHtml(row.last_error)}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="empty">Nenhuma operação YARA-X registrada.</td></tr>';
  }

  async function load() {
    $('status-text').textContent = 'Atualizando segurança YARA-X…';
    const response = await fetch(`/api/admin/security/yara-x?${query()}`, requestOptions({headers:controllerHeaders()}));
    if (!response.ok) {
      $('status-text').textContent = `Falha ao carregar YARA-X (${response.status}).`;
      return;
    }
    const data = await response.json();
    const summary = data.summary || {};
    $('status-text').textContent = `${summary.agents_ready || 0} de ${summary.agents_total || 0} Agents com scanner pronto`;
    $('summary').innerHTML = [
      card('Agents', summary.agents_total || 0, `${summary.agents_ready || 0} ready · ${summary.agents_not_ready || 0} not ready`),
      card('Scans recentes', summary.recent_scans || 0, 'Universal Event Platform'),
      card('Clean', summary.results?.clean || 0),
      card('Suspicious', summary.results?.suspicious || 0),
      card('Blocked', summary.results?.blocked || 0),
      card('Scan failed', summary.results?.scan_failed || 0),
    ].join('');
    renderAgents(data.agents || []);
    renderEvents(data.events || []);
    await loadOperations();
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-yarax-action]');
    if (button) runOperation(button);
  });
  $('refresh').addEventListener('click', load);
  $('apply').addEventListener('click', load);
  load().catch((error) => {
    $('status-text').textContent = `Falha: ${error.message}`;
  });
})();
