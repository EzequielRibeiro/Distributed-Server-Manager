(() => {
  const $ = (id) => document.getElementById(id);
  const headers = () => ({'Accept':'application/json','Content-Type':'application/json','X-Capivara-Auth-Area':'controller'});
  const options = (extra={}) => ({headers:headers(),credentials:'same-origin',cache:'no-store',...extra});
  const esc = (v) => String(v ?? '—').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const bytes = (n) => { let v=Number(n||0),u=['B','KB','MB','GB','TB'],i=0; while(v>=1024&&i<u.length-1){v/=1024;i++;} return `${v.toFixed(i?2:0)} ${u[i]}`; };
  const num = (n) => Number(n||0).toLocaleString('pt-BR');
  const TABLE_LABELS = {
    observability_samples:'Histórico de telemetria',
    universal_events:'Eventos do sistema',
    instance_telemetry_samples:'Telemetria das instâncias',
    backup_jobs:'Tarefas de backup',
    dashboard_activity_log:'Atividade do painel',
    observability_latest:'Estado atual da telemetria',
    instance_file_commands:'Comandos de arquivos',
    activity_audit:'Auditoria de atividades',
    agent_instance_commands:'Comandos de instância',
    alerts:'Alertas',
    customers:'Clientes',
    instance_ports:'Portas das instâncias',
    agent_instance_provisioning:'Provisionamento de instâncias',
    agent_pairing_tokens:'Tokens de pareamento',
    artifact_transfers:'Transferências de artefatos',
    agent_port_ranges:'Faixas de portas dos Agents',
    deleted_instance_backups:'Backups de instâncias excluídas',
    instances:'Instâncias',
    alert_events:'Eventos de alerta',
    agent_credentials:'Credenciais de Agents',
    database_metrics_daily:'Histórico do Data Mine'
  };
  const CAPABILITY_LABELS = {
    health:'Saúde do banco',
    storage:'Armazenamento',
    growth_snapshots:'Histórico de crescimento',
    datamine:'Análise Data Mine',
    retention_control:'Controle de retenção',
    analyze:'Atualização de estatísticas',
    index_scan_stats:'Estatísticas de uso de índices',
    lock_wait_stats:'Locks em espera',
    query_duration_stats:'Duração de consultas',
    precise_table_bytes:'Tamanho preciso por tabela',
    historical_snapshots:'Snapshots históricos',
    physical_reclaim_action:'Recuperação física automática'
  };
  const METRIC_LABELS = {
    'capivara.host.memory.usage_pct':'Uso de memória do host',
    'host.memory.usage_pct':'Uso de memória do host',
    'capivara.host.disk.usage_pct':'Uso de disco do host',
    'host.disk.usage_pct':'Uso de disco do host',
    'host.network.rx_bytes':'Rede recebida',
    'host.network.tx_bytes':'Rede enviada',
    'host.uptime_seconds':'Tempo ligado do host',
    'agent.memory.rss_bytes':'Memória do Agent',
    'agent.threads':'Threads do Agent',
    'capivara.agent.pid':'Processo do Agent',
    'host.load.1m':'Carga do host · 1 min',
    'host.load.5m':'Carga do host · 5 min',
    'host.load.15m':'Carga do host · 15 min'
  };
  const healthLabel = (value) => ({healthy:'Saudável',degraded:'Atenção',critical:'Crítico',error:'Erro'}[String(value||'').toLowerCase()] || value || '—');
  const identifierLabel = (value, type='generic') => {
    const raw=String(value||'').trim();
    if (!raw) return '—';
    if (type==='table' && TABLE_LABELS[raw]) return TABLE_LABELS[raw];
    if (type==='metric' && METRIC_LABELS[raw]) return METRIC_LABELS[raw];
    if (type==='capability' && CAPABILITY_LABELS[raw]) return CAPABILITY_LABELS[raw];
    return raw
      .replace(/^capivara[._-]/i,'')
      .replace(/[._-]+/g,' ')
      .replace(/\b(agent|agents)\b/gi,'Agent')
      .replace(/\b(api)\b/gi,'API')
      .replace(/\b(db)\b/gi,'DB')
      .replace(/\b(id)\b/gi,'ID')
      .replace(/\bpct\b/gi,'%')
      .replace(/\bbytes\b/gi,'bytes')
      .replace(/\b\w/g,c=>c.toUpperCase());
  };
  const friendlyCell = (raw, type='generic') => `<span class="friendly-name" title="${esc(raw)}">${esc(identifierLabel(raw,type))}</span>`;

  async function api(mode='overview') {
    const days = $('growth-days')?.value || '90';
    const r = await fetch(`/api/admin/database-intelligence?mode=${encodeURIComponent(mode)}&days=${encodeURIComponent(days)}`, options());
    if (r.status===401) { location.replace('/login.html'); throw new Error('Sessão encerrada'); }
    const body = await r.json();
    if (!r.ok) throw new Error(body.message || body.error || `HTTP ${r.status}`);
    return body;
  }
  async function action(actionName) {
    const r = await fetch('/api/admin/database-intelligence/action', options({method:'POST',body:JSON.stringify({action:actionName})}));
    const body = await r.json();
    if (!r.ok) throw new Error(body.message || body.error || `HTTP ${r.status}`);
    return body;
  }
  async function loadShell() {
    const r = await fetch('/components/sidebar-v3.html', options());
    if (!r.ok) throw new Error('Falha ao carregar navegação');
    $('sidebar-component').innerHTML = await r.text();
    document.querySelectorAll('#sidebar-component nav a').forEach(a=>a.classList.toggle('active',(a.getAttribute('href')||'').includes('database-intelligence')));
    const who = await fetch('/api/whoami', options());
    if (who.status===401) { location.replace('/login.html'); return; }
    const user = await who.json(), role=String(user.role||'').toLowerCase();
    $('dbi-user-name').textContent=user.username||'—'; $('dbi-user-role').textContent=user.role||'—';
    document.querySelectorAll('.admin-only').forEach(el=>el.style.display=role==='admin'?'':'none');
    document.querySelectorAll('.agent-manager-only').forEach(el=>el.style.display=['admin','controller'].includes(role)?'':'none');
    $('btn-logout')?.addEventListener('click',async()=>{try{await fetch('/api/auth/logout',options({method:'POST'}));}finally{location.replace('/login.html');}});
    $('dbi-menu-toggle')?.addEventListener('click',()=>document.body.classList.toggle(window.innerWidth<=760?'sidebar-open':'cap-sidebar-collapsed'));
  }
  function card(label,value,detail=''){return `<article class="metric-card"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small></article>`;}
  function renderSummary(data){
    const h=data.health,p=data.profile,r=data.retention;
    $('summary').innerHTML=[
      card('Backend',String(h.backend||'').toUpperCase(),h.server_version||''),
      card('Tamanho',bytes(h.database_size_bytes),h.database_name||''),
      card('Saúde',healthLabel(h.health),`${h.latency_ms} ms`),
      card('Conexões',`${h.connections.active}/${h.connections.max}`,`${h.connections.utilization_pct}%`),
      card('Histórico',num(p.historical_samples),'observability_samples'),
      card('Estado atual',num(p.latest_projection_rows),'observability_latest'),
      card('Retenção',`${r.retention_days} dias`,`${r.history_interval_seconds/60} min por bucket`),
      card('Pendentes',num(r.pending_rows),'linhas fora da retenção')
    ].join('');
    $('dbi-status').textContent=`Banco ${healthLabel(h.health).toLowerCase()} · ${bytes(h.database_size_bytes)} · ${String(h.backend||'').toUpperCase()}`;
  }
  function renderGrowth(g){
    const rows=g.series||[], box=$('growth-chart');
    if(rows.length<2){box.innerHTML='<p class="empty">Snapshots históricos insuficientes. O worker começará a formar a série diariamente.</p>';}
    else{
      const w=760,h=230,p=28,vals=rows.map(x=>Number(x.database_size_bytes||0)),min=Math.min(...vals),max=Math.max(...vals),range=Math.max(1,max-min);
      const pts=rows.map((r,i)=>{const x=p+(w-2*p)*(i/Math.max(1,rows.length-1)),y=h-p-(h-2*p)*((Number(r.database_size_bytes)-min)/range);return [x,y];});
      const path=pts.map((q,i)=>(i?'L':'M')+q[0].toFixed(1)+' '+q[1].toFixed(1)).join(' ');
      const area=path+` L ${pts.at(-1)[0]} ${h-p} L ${pts[0][0]} ${h-p} Z`;
      box.innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Crescimento do banco"><line class="chart-grid" x1="${p}" y1="${h-p}" x2="${w-p}" y2="${h-p}"/><path class="chart-fill" d="${area}"/><path class="chart-line" d="${path}"/><text class="chart-label" x="${p}" y="16">${esc(bytes(max))}</text><text class="chart-label" x="${p}" y="${h-5}">${esc(rows[0].day)}</text><text class="chart-label" text-anchor="end" x="${w-p}" y="${h-5}">${esc(rows.at(-1).day)}</text></svg>`;
    }
    $('forecast').innerHTML=[7,30,90].map(d=>`<div><small>Projeção ${d}d</small><strong>${esc(bytes(g.forecast_bytes?.[String(d)]||0))}</strong></div>`).join('');
  }
  function bars(target,rows,nameKey,valueKey,formatter=bytes,labelType='generic'){
    const max=Math.max(1,...rows.map(r=>Number(r[valueKey]||0)));
    target.innerHTML=rows.length?rows.map(r=>`<div class="bar-row"><span title="${esc(r[nameKey])}">${esc(identifierLabel(r[nameKey],labelType))}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(1,Number(r[valueKey]||0)*100/max)}%"></div></div><strong>${esc(formatter(r[valueKey]))}</strong></div>`).join(''):'<p class="empty">Sem dados.</p>';
  }
  function rank(target,rows,nameKey,labelType='generic'){
    const max=Math.max(1,...rows.map(r=>Number(r.samples||0)));
    target.innerHTML=rows.length?rows.slice(0,12).map(r=>`<div class="rank-row"><span title="${esc(r[nameKey])}">${esc(identifierLabel(r[nameKey],labelType))}</span><div class="bar-track"><div class="bar-fill" style="width:${Number(r.samples||0)*100/max}%"></div></div><strong>${esc(num(r.samples))}</strong></div>`).join(''):'<p class="empty">Sem dados.</p>';
  }
  function renderTables(rows){
    $('tables').innerHTML=rows.length?rows.map(r=>`<tr><td data-label="Tabela">${friendlyCell(r.table_name,'table')}</td><td data-label="Linhas">${esc(num(r.row_count))}</td><td data-label="Dados">${esc(bytes(r.data_size_bytes))}</td><td data-label="Índices">${esc(bytes(r.index_size_bytes))}</td><td data-label="Total">${esc(bytes(r.total_size_bytes))}</td><td data-label="Dead rows">${esc(r.dead_ratio_pct)}%</td></tr>`).join(''):'<tr><td colspan="6" class="empty">Sem dados.</td></tr>';
  }
  function renderInsights(rows){$('insights').innerHTML=(rows||[]).map(x=>`<article class="insight ${esc(x.severity)}"><strong>${esc(x.title)}</strong><p>${esc(x.message)}</p></article>`).join('')||'<p class="empty">Sem insights.</p>';}
  function renderCapabilities(c){$('capabilities').innerHTML=Object.entries(c).filter(([k])=>k!=='backend').map(([k,v])=>`<div class="capability"><span title="${esc(k)}">${esc(identifierLabel(k,'capability'))}</span><strong class="${v?'ok':'no'}">${v?'✓':'—'}</strong></div>`).join('');}
  function renderRetention(r){$('retention-summary').innerHTML=[
    ['Retenção',r.retention_days+' dias'],['Bucket histórico',(r.history_interval_seconds/60)+' min'],['Batch',num(r.batch_size)],['Worker',r.worker_seconds+' s'],['Pendentes',num(r.pending_rows)],['Cutoff',r.cutoff]
  ].map(x=>`<div><small>${esc(x[0])}</small><strong>${esc(x[1])}</strong></div>`).join('');}
  async function load(){
    $('dbi-status').textContent='Atualizando Database Intelligence…';
    try{
      const data=await api('overview');
      renderSummary(data); renderGrowth(data.growth);
      bars($('storage-chart'),(data.storage.tables||[]).slice(0,10),'table_name','total_size_bytes',bytes,'table');
      rank($('agent-producers'),data.profile.by_agent||[],'agent_id'); rank($('metric-producers'),data.profile.by_metric||[],'metric_name','metric');
      renderInsights(data.insights); renderCapabilities(data.capabilities); renderRetention(data.retention); renderTables(data.storage.tables||[]);
      const mine=await api('datamine');
      $('indexes').innerHTML=(mine.indexes||[]).slice(0,30).map(r=>`<tr><td data-label="Índice">${friendlyCell(r.index_name)}</td><td data-label="Tabela">${friendlyCell(r.table_name,'table')}</td><td data-label="Leituras">${esc(num(r.scans))}</td><td data-label="Tamanho">${esc(bytes(r.size_bytes))}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">Dados de índice não disponíveis.</td></tr>';
    }catch(e){$('dbi-status').textContent='Falha: '+e.message;}
  }
  async function runAction(name){
    const out=$('action-result'); out.textContent='Executando '+name+'…';
    try{const result=await action(name);out.textContent=JSON.stringify(result,null,2);await load();}catch(e){out.textContent='Erro: '+e.message;}
  }
  document.addEventListener('DOMContentLoaded',async()=>{
    await loadShell();
    $('refresh').onclick=load; $('growth-days').onchange=load;
    $('preview-retention').onclick=()=>runAction('retention-preview');
    $('run-retention').onclick=()=>runAction('retention-run');
    $('capture-snapshot').onclick=()=>runAction('snapshot');
    $('analyze-db').onclick=()=>runAction('analyze');
    await load();
  });
})();