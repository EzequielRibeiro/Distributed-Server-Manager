(() => {
  const $ = (id) => document.getElementById(id);
  const controllerHeaders = () => ({'Accept':'application/json','X-Capivara-Auth-Area':'controller'});
  const requestOptions = () => ({headers:controllerHeaders(),credentials:'same-origin',cache:'no-store'});
  const text = (value) => value === null || value === undefined || value === '' ? '—' : String(value);
  async function loadShell() {
    const sidebar = $('sidebar-component');
    const response = await fetch('/components/sidebar-v3.html', requestOptions({headers:controllerHeaders()}));
    if (response.status === 401) { window.location.replace('/login.html'); throw new Error('Sessão encerrada'); }
    if (!response.ok) throw new Error(`sidebar HTTP ${response.status}`);
    sidebar.innerHTML = await response.text();
    sidebar.querySelectorAll('nav a').forEach((link) => link.classList.toggle('active', link.getAttribute('href') === 'observability.html'));

    const who = await fetch('/api/whoami', requestOptions({headers:controllerHeaders()}));
    if (who.status === 401) { window.location.replace('/login.html'); throw new Error('Sessão encerrada'); }
    const user = await who.json();
    const role = String(user.role || '').toLowerCase();
    $('admin-observability-user-name').textContent = user.username || '—';
    $('admin-observability-user-role').textContent = user.role || '—';
    document.querySelectorAll('.admin-only').forEach((element) => { element.style.display = role === 'admin' ? '' : 'none'; });
    document.querySelectorAll('.agent-manager-only').forEach((element) => { element.style.display = ['admin','controller'].includes(role) ? '' : 'none'; });
    document.querySelectorAll('.instance-manager-only').forEach((element) => { element.style.display = ['admin','controller','client','customer'].includes(role) ? '' : 'none'; });

    const logout = $('btn-logout');
    if (logout) logout.onclick = async () => {
      try { await fetch('/api/auth/logout', {method:'POST',headers:controllerHeaders(),credentials:'same-origin',cache:'no-store'}); }
      finally { window.location.replace('/login.html'); }
    };

    const toggle = $('admin-observability-menu-toggle');
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

  function placementDiagnosis(detail) {
    const rejected = Array.isArray(detail?.technical_rejections) ? detail.technical_rejections : [];
    const agents = rejected.map((item) => {
      const agent = item.name || item.node_id || item.agent_id || 'Agent';
      const reasons = Array.isArray(item.reasons) ? item.reasons.join(', ') : '';
      const status = item.status ? ` [${item.status}]` : '';
      return `${agent}${status}: ${reasons || 'sem motivo detalhado'}`;
    });
    if (agents.length) return agents.join(' • ');
    return detail?.placement_reason || 'Placement indisponível sem rejeições técnicas registradas.';
  }

  function renderCustomerProblems(incidents) {
    const target = $('customer-problems');
    const rows = (incidents || []).filter((item) => item.rule_id === 'CUSTOMER_INSTANCE_PLACEMENT_BLOCKED');
    if (!rows.length) {
      target.innerHTML = '<tr><td colspan="8" class="empty">Nenhum cliente impedido de provisionar.</td></tr>';
      return;
    }
    target.innerHTML = rows.map((incident) => {
      const detail = incident.admin_details || {};
      const customer = detail.customer_name || detail.customer_code || incident.customer_id;
      const runtime = [detail.game, detail.runtime_id].filter(Boolean).join(' / ');
      const region = [detail.country_code, detail.region_name || detail.region_id].filter(Boolean).join(' · ');
      return `<tr>
        <td>${escapeHtml(incident.level)}</td>
        <td>${escapeHtml(customer)}</td>
        <td>${escapeHtml(detail.contract_id)}</td>
        <td>${escapeHtml(runtime)}</td>
        <td>${escapeHtml(region)}</td>
        <td>${escapeHtml(placementDiagnosis(detail))}</td>
        <td>${escapeHtml(detail.occurrence_count || 1)}</td>
        <td>${escapeHtml(detail.last_attempt_at || incident.updated_at || incident.opened_at)}</td>
      </tr>`;
    }).join('');
  }

  async function loadCustomerProblems() {
    const params = new URLSearchParams({active: 'true', limit: '200'});
    const customer = $('customer-filter').value.trim();
    if (customer) params.set('customer_id', customer);
    const response = await fetch(`/api/admin/customer-health?${params}`, requestOptions());
    if (!response.ok) throw new Error(`customer health ${response.status}`);
    const data = await response.json();
    renderCustomerProblems(data.incidents || []);
    return data;
  }

  async function load() {
    $('health-text').textContent = 'Atualizando visão consolidada…';
    const suffix = query();
    const [response, customerHealth] = await Promise.all([
      fetch(`/api/admin/observability${suffix ? `?${suffix}` : ''}`, requestOptions()),
      loadCustomerProblems().catch((error) => {
        $('customer-problems').innerHTML = `<tr><td colspan="8" class="empty">Falha ao carregar incidentes: ${escapeHtml(error.message)}</td></tr>`;
        return null;
      }),
    ]);
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
      card('Clientes com problema', customerHealth?.customers_with_problems ?? alerts.customer_problems ?? 0, 'incidentes funcionais ativos'),
      card('Filas', queues.metrics ?? 0, `${queues.potentially_stuck ?? 0} sinais potencialmente travados`),
    ].join('');

    renderRows($('operations'), data.recent?.operations || [], ['operation_type','status','agent_id','instance_id','correlation_id']);
    renderRows($('alerts'), data.recent?.alerts || [], ['severity','code','scope','status','correlation_id']);
    renderRows($('activity'), data.recent?.activity || [], ['actor','role','action',(row) => `${text(row.target_type)}:${text(row.target_id)}`,'correlation_id']);
  }

  $('refresh').addEventListener('click', load);
  $('apply').addEventListener('click', load);
  loadShell()
    .then(load)
    .catch((error) => { $('health-text').textContent = `Falha: ${error.message}`; });
  setInterval(() => load().catch(() => {}), 30000);
})();
