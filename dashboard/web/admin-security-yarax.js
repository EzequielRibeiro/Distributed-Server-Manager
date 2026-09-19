(() => {
  const $ = (id) => document.getElementById(id);
  const controllerHeaders = (extra = {}) => ({'Accept':'application/json','X-Capivara-Auth-Area':'controller',...extra});
  const requestOptions = (extra = {}) => ({credentials:'same-origin',cache:'no-store',...extra});
  const text = (value) => value === null || value === undefined || value === '' ? '—' : String(value);
  const LIVE_REFRESH_MS = 10000;
  let loadInFlight = false;
  async function loadShell() {
    const sidebar = $('sidebar-component');
    const response = await fetch('/components/sidebar-v3.html', requestOptions({headers:controllerHeaders()}));
    if (response.status === 401) { window.location.replace('/login.html'); throw new Error('Sessão encerrada'); }
    if (!response.ok) throw new Error(`sidebar HTTP ${response.status}`);
    sidebar.innerHTML = await response.text();
    sidebar.querySelectorAll('nav a').forEach((link) => link.classList.toggle('active', link.getAttribute('href') === 'admin-security-yarax.html'));

    const who = await fetch('/api/whoami', requestOptions({headers:controllerHeaders()}));
    if (who.status === 401) { window.location.replace('/login.html'); throw new Error('Sessão encerrada'); }
    const user = await who.json();
    const role = String(user.role || '').toLowerCase();
    $('yarax-user-name').textContent = user.username || '—';
    $('yarax-user-role').textContent = user.role || '—';
    document.querySelectorAll('.admin-only').forEach((element) => { element.style.display = role === 'admin' ? '' : 'none'; });
    document.querySelectorAll('.agent-manager-only').forEach((element) => { element.style.display = ['admin','controller'].includes(role) ? '' : 'none'; });
    document.querySelectorAll('.instance-manager-only').forEach((element) => { element.style.display = ['admin','controller','client','customer'].includes(role) ? '' : 'none'; });

    const logout = $('btn-logout');
    if (logout) logout.onclick = async () => {
      try { await fetch('/api/auth/logout', {method:'POST',headers:controllerHeaders(),credentials:'same-origin',cache:'no-store'}); }
      finally { window.location.replace('/login.html'); }
    };

    const toggle = $('yarax-menu-toggle');
    const setOpen = (open) => {
      const mobile = window.innerWidth <= 760;
      document.body.classList.toggle('sidebar-open', Boolean(open) && mobile);
      if (!mobile) document.body.classList.toggle('cap-sidebar-collapsed', Boolean(open));
    };
    if (toggle) toggle.addEventListener('click', () => {
      if (window.innerWidth <= 760) document.body.classList.toggle('sidebar-open');
      else document.body.classList.toggle('cap-sidebar-collapsed');
    });
    sidebar.querySelector('.cap-sidebar-close')?.addEventListener('click', () => document.body.classList.remove('sidebar-open'));
    sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => document.body.classList.remove('sidebar-open')));
  }

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
      <td data-label="Agent"><strong>${escapeHtml(row.name || row.agent_id)}</strong><small>${escapeHtml(row.agent_id)}</small></td>
      <td data-label="Saúde">${badge(row.health_status || 'offline')}</td>
      <td data-label="Scanner">${badge(row.state || 'unknown')}</td>
      <td data-label="Engine">${escapeHtml(row.engine_version)}${row.engine_managed ? '<small>managed</small>' : ''}</td>
      <td data-label="Ruleset">${escapeHtml(row.ruleset_version)}${row.rules_managed ? '<small>managed</small>' : ''}</td>
      <td data-label="Regras">${escapeHtml(row.rules_count)}</td>
      <td data-label="Checksum">${badge(row.ruleset_checksum_valid === true ? 'valid' : row.ruleset_checksum_valid === false ? 'invalid' : 'unknown')}</td>
      <td data-label="Último erro" class="error-cell">${escapeHtml(row.last_error)}</td>
      <td data-label="Operações" class="operation-buttons">
        <button type="button" data-yarax-action="install_engine" data-agent-id="${escapeHtml(row.agent_id)}">Engine</button>
        <button type="button" data-yarax-action="install_rules" data-agent-id="${escapeHtml(row.agent_id)}">Regras</button>
        <button type="button" data-yarax-action="test_scan" data-agent-id="${escapeHtml(row.agent_id)}">Teste</button>
        <button type="button" data-yarax-action="rollback_rules" data-agent-id="${escapeHtml(row.agent_id)}">Rollback</button>
      </td>
    </tr>`).join('') : '<tr><td colspan="8" class="empty">Nenhum Agent encontrado.</td></tr>';
  }

  function detectionDetails(row) {
    const matches = Array.isArray(row.matches) ? row.matches : [];
    if (!matches.length) return '<span class="muted">—</span>';
    const summary = matches[0]?.detection_name || matches[0]?.threat_name || matches[0]?.rule || `${matches.length} match(es)`;
    const items = matches.map((match) => {
      const labels = [];
      if (match.threat_name) labels.push(`Ameaça: ${escapeHtml(match.threat_name)}`);
      if (match.malware_family) labels.push(`Família: ${escapeHtml(match.malware_family)}`);
      if (match.category) labels.push(`Categoria: ${escapeHtml(match.category)}`);
      labels.push(`Regra: ${escapeHtml(match.rule || 'unknown')}`);
      if (Array.isArray(match.tags) && match.tags.length) labels.push(`Tags: ${match.tags.map(escapeHtml).join(' · ')}`);
      if (match.description && match.description !== match.detection_name) labels.push(`Descrição: ${escapeHtml(match.description)}`);
      if (match.relative_path) labels.push(`Arquivo: ${escapeHtml(match.relative_path)}`);
      return `<li><strong>${escapeHtml(match.detection_name || match.rule || 'Detecção')}</strong><small>${labels.join('<br>')}</small></li>`;
    }).join('');
    return `<details class="detection-details"><summary>${escapeHtml(summary)}${matches.length > 1 ? ` (+${matches.length - 1})` : ''}</summary><ul>${items}</ul></details>`;
  }

  function matchedFile(row) {
    const files = Array.isArray(row.matched_files) ? row.matched_files.filter(Boolean) : [];
    if (!files.length) return '—';
    if (files.length === 1) return escapeHtml(files[0]);
    return `<details class="matched-files"><summary>${escapeHtml(files[0])} (+${files.length - 1})</summary><ul>${files.map((file) => `<li>${escapeHtml(file)}</li>`).join('')}</ul></details>`;
  }

  function renderEvents(rows) {
    $('events').innerHTML = rows.length ? rows.map((row) => `<tr>
      <td data-label="Data">${escapeHtml(row.occurred_at)}</td>
      <td data-label="Agent">${escapeHtml(row.agent_id)}</td>
      <td data-label="Instância">${escapeHtml(row.instance_id)}</td>
      <td data-label="Conteúdo"><strong>${escapeHtml(row.content_id)}</strong><small>${escapeHtml(row.provider || row.game_id)}</small></td>
      <td data-label="Arquivo" class="file-cell">${matchedFile(row)}</td>
      <td data-label="Resultado">${badge(row.result || row.event_type)}</td>
      <td data-label="Detecção" class="detection-cell">${detectionDetails(row)}</td>
      <td data-label="Duração">${row.duration_ms === null || row.duration_ms === undefined ? '—' : escapeHtml(row.duration_ms + ' ms')}</td>
      <td data-label="Erro" class="error-cell">${escapeHtml(row.error)}
        ${row.agent_id && row.instance_id && row.content_id ? `<button type="button" class="rescan" data-yarax-action="rescan_content" data-agent-id="${escapeHtml(row.agent_id)}" data-instance-id="${escapeHtml(row.instance_id)}" data-content-id="${escapeHtml(row.content_id)}">Re-scan</button>` : ''}
      </td>
    </tr>`).join('') : '<tr><td colspan="9" class="empty">Nenhum evento YARA-X encontrado.</td></tr>';
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
      <td data-label="Data">${escapeHtml(row.created_at)}</td>
      <td data-label="Agent">${escapeHtml(row.agent_id)}</td>
      <td data-label="Ação">${escapeHtml(row.action)}</td>
      <td data-label="Status">${badge(row.status)}</td>
      <td data-label="Alvo">${escapeHtml([row.instance_id,row.content_id].filter(Boolean).join(' / '))}</td>
      <td data-label="Erro" class="error-cell">${escapeHtml(row.last_error)}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="empty">Nenhuma operação YARA-X registrada.</td></tr>';
  }

  async function load({silent=false} = {}) {
    if (loadInFlight) return;
    loadInFlight = true;
    try {
      if (!silent) $('status-text').textContent = 'Atualizando segurança YARA-X…';
      const response = await fetch(`/api/admin/security/yara-x?${query()}`, requestOptions({headers:controllerHeaders()}));
      if (!response.ok) {
        $('status-text').textContent = `Falha ao carregar YARA-X (${response.status}).`;
        return;
      }
      const data = await response.json();
      const summary = data.summary || {};
      $('status-text').textContent = `${summary.agents_ready || 0} de ${summary.agents_total || 0} Agents com scanner pronto · atualização automática 10s`;
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
    } finally {
      loadInFlight = false;
    }
  }

  async function liveRefresh() {
    if (document.hidden) return;
    try { await load({silent:true}); }
    catch (error) {
      loadInFlight = false;
      $('status-text').textContent = `Falha na atualização automática: ${error.message}`;
    }
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-yarax-action]');
    if (button) runOperation(button);
  });
  $('refresh').addEventListener('click', () => load());
  $('apply').addEventListener('click', () => load());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) liveRefresh(); });
  setInterval(liveRefresh, LIVE_REFRESH_MS);
  loadShell()
    .then(() => load())
    .catch((error) => { $('status-text').textContent = `Falha: ${error.message}`; });
})();
