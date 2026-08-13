const state = { gameType: 'minecraft', currentServer: 'Aurora SMP' };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 2400);
}

function setView(name) {
  $$('.section-tab').forEach(button => button.classList.toggle('active', button.dataset.view === name));
  $$('.view').forEach(view => view.classList.toggle('active', view.id === `view-${name}`));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

$$('.section-tab').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
$$('[data-open-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.openView)));

const serverProfiles = {
  'Aurora SMP': ['MINECRAFT · PAPER 1.21.1', 'mc.aurora.capivara.host:25565'],
  'Ilha Ferrugem': ['RUST · VANILLA 2580', 'rust.capivara.host:28015'],
  'Chernarus BR': ['DAYZ · EXPANSION 1.26', 'dayz.capivara.host:2302'],
  'Operação Javali': ['ARMA 3 · ANTISTASI ULTIMATE', 'arma.capivara.host:2302']
};

const minecraftSettings = $('#settings-form').innerHTML;
const gameSettings = {
  Rust: {
    profile: 'PERFIL RUST', title: 'Mapa, wipe e jogabilidade', file: 'server.cfg',
    fields: [['Nome do servidor', 'Ilha Ferrugem'], ['Porta do jogo', '28015'], ['Tamanho do mapa', '3500'], ['Seed do mapa', '742019'], ['Máximo de jogadores', '100'], ['Intervalo de salvamento', '300 s']],
    toggles: [['Oxide/uMod', 'Carregar plugins da comunidade'], ['PvP', 'Dano entre jogadores'], ['Anti-cheat', 'Easy Anti-Cheat'], ['Wipe automático', 'Agenda mensal']]
  },
  DayZ: {
    profile: 'PERFIL DAYZ', title: 'Missão, economia e sobrevivência', file: 'serverDZ.cfg',
    fields: [['Nome do servidor', 'Chernarus BR'], ['Porta do jogo', '2302'], ['Missão', 'dayzOffline.chernarusplus'], ['Slots', '60'], ['Time acceleration', '6x'], ['Persistência', 'profiles/']],
    toggles: [['Whitelist', 'Acesso por lista'], ['BattlEye', 'Proteção anticheat'], ['3ª pessoa', 'Câmera alternativa'], ['Mods Workshop', 'Coleção sincronizada']]
  },
  'Arma 3': {
    profile: 'PERFIL ARMA 3', title: 'Missão, mods e parâmetros', file: 'server.cfg',
    fields: [['Nome do servidor', 'Operação Javali'], ['Porta do jogo', '2302'], ['Missão', 'Antistasi Altis'], ['Slots', '32'], ['Dificuldade', 'Custom'], ['Mods', '@CBA_A3;@ACE']],
    toggles: [['BattlEye', 'Proteção anticheat'], ['Assinaturas v2', 'Validar mods'], ['Voz sobre rede', 'VoN habilitado'], ['Headless client', 'IA distribuída']]
  }
};

function renderSettings(game) {
  const panel = $('#settings-form');
  if (game === 'Minecraft') { panel.innerHTML = minecraftSettings; return; }
  const config = gameSettings[game];
  panel.innerHTML = `<div class="panel-heading"><div><span class="panel-kicker">${config.profile}</span><h2>${config.title}</h2><p>Campos amigáveis sincronizados com <code>${config.file}</code>.</p></div><span class="saved-state">✓ Salvo</span></div>
    <div class="form-grid">${config.fields.map(([label, value]) => `<label>${label}<input value="${value}"></label>`).join('')}</div>
    <div class="switch-grid">${config.toggles.map(([label, help], index) => `<label><input type="checkbox" ${index < 3 ? 'checked' : ''}><span></span><b>${label}</b><small>${help}</small></label>`).join('')}</div>
    <label class="full-field">Parâmetros adicionais<textarea>${game === 'Rust' ? '+server.secure 1 +server.encryption 1' : game === 'DayZ' ? '-profiles=profiles -dologs -adminlog' : '-autoInit -loadMissionToMemory'}</textarea></label>
    <div class="form-footer"><span>O Capivara valida os parâmetros antes de reiniciar.</span><button class="primary">Salvar alterações</button></div>`;
}

$$('.server-item').forEach(button => button.addEventListener('click', () => {
  $$('.server-item').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  state.currentServer = button.dataset.server;
  $('#server-title').childNodes[0].textContent = `${button.dataset.server} `;
  $('#breadcrumb-name').textContent = button.dataset.server;
  $('#game-label').textContent = serverProfiles[button.dataset.server][0];
  $('.server-header p').childNodes[0].textContent = `${serverProfiles[button.dataset.server][1]} `;
  $('.live-badge').textContent = button.querySelector('.status').classList.contains('offline') ? 'OFFLINE' : 'ONLINE';
  renderSettings(button.dataset.game);
  document.documentElement.style.setProperty('--green', button.dataset.color);
  showToast(`${button.dataset.game}: perfil específico carregado`);
  if (window.innerWidth <= 720) $('.sidebar').classList.remove('open');
}));

$('#mobile-menu').addEventListener('click', () => $('.sidebar').classList.toggle('open'));
$$('.copy-btn').forEach(button => button.addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(button.dataset.copy); showToast('Endereço copiado'); }
  catch { showToast('Endereço pronto para copiar'); }
}));

const players = ['BiaLima', 'MestreLobo', 'Joao_V', 'CapiBuilds', 'NandaXP', 'RedstoneBR', 'AriCraft', 'Guto_77'];
$('#player-list').innerHTML = players.map((name, index) => `<div class="player-line"><i>${name.slice(0, 2).toUpperCase()}</i><span>${name}</span><small>${22 + index * 4} ms</small></div>`).join('');

$('#command-form').addEventListener('submit', event => {
  event.preventDefault();
  const input = $('#command-input');
  const command = input.value.trim();
  if (!command) return;
  const terminal = $('#terminal');
  terminal.innerHTML += `\n<span class="time">agora</span> <span class="capy">[Você]</span> ${command.replace(/[<>]/g, '')}\n<span class="time">agora</span> <span class="ok">[Servidor]</span> Comando recebido pelo protótipo`;
  terminal.scrollTop = terminal.scrollHeight;
  input.value = '';
});

const modal = $('#server-modal');
function openModal() { modal.classList.add('open'); modal.setAttribute('aria-hidden', 'false'); document.body.style.overflow = 'hidden'; }
function closeModal() { modal.classList.remove('open'); modal.setAttribute('aria-hidden', 'true'); document.body.style.overflow = ''; }
['#new-server-btn', '#import-open', '#import-open-2'].forEach(selector => $(selector)?.addEventListener('click', openModal));
$$('[data-close-modal]').forEach(element => element.addEventListener('click', closeModal));
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeModal(); });

$$('[data-modal-mode]').forEach(button => button.addEventListener('click', () => {
  $$('[data-modal-mode]').forEach(item => item.classList.toggle('active', item === button));
  const importing = button.dataset.modalMode === 'import';
  $('#import-flow').hidden = !importing;
  $('#create-flow').hidden = importing;
  $('#modal-title').textContent = importing ? 'Importar arquivos existentes' : 'Criar um novo servidor';
}));

const hints = {
  minecraft: 'Detectamos Paper, Spigot, Fabric, Forge e Vanilla pelo conteúdo.',
  rust: 'Procuraremos RustDedicated, server.cfg, mapas e plugins Oxide/uMod.',
  dayz: 'Procuraremos serverDZ.cfg, missões, perfis, keys e mods Workshop.',
  arma: 'Procuraremos arma3server, server.cfg, missões e parâmetros de inicialização.'
};
$$('#game-cards button').forEach(button => button.addEventListener('click', () => {
  $$('#game-cards button').forEach(item => item.classList.remove('selected'));
  button.classList.add('selected');
  state.gameType = button.dataset.gameType;
  $('#format-hint').textContent = hints[state.gameType];
}));

const fileInput = $('#server-files');
const archiveInput = $('#server-archive');
const dropZone = $('#drop-zone');
$('#browse-files').addEventListener('click', event => { event.stopPropagation(); fileInput.click(); });
$('#browse-archive').addEventListener('click', event => { event.stopPropagation(); archiveInput.click(); });
dropZone.addEventListener('click', event => { if (!['browse-files', 'browse-archive'].includes(event.target.id)) fileInput.click(); });
dropZone.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') fileInput.click(); });
['dragenter', 'dragover'].forEach(type => dropZone.addEventListener(type, event => { event.preventDefault(); dropZone.classList.add('dragging'); }));
['dragleave', 'drop'].forEach(type => dropZone.addEventListener(type, event => { event.preventDefault(); dropZone.classList.remove('dragging'); }));
dropZone.addEventListener('drop', event => acceptFiles(event.dataTransfer.files));
fileInput.addEventListener('change', () => acceptFiles(fileInput.files));
archiveInput.addEventListener('change', () => acceptFiles(archiveInput.files));

function acceptFiles(files) {
  if (!files?.length) return;
  const total = [...files].reduce((sum, file) => sum + file.size, 0);
  const size = total > 1024 ** 3 ? `${(total / 1024 ** 3).toFixed(1)} GB` : `${Math.max(1, total / 1024 ** 2).toFixed(1)} MB`;
  dropZone.innerHTML = `<span class="upload-icon">✓</span><strong>${files.length} arquivo${files.length > 1 ? 's' : ''} selecionado${files.length > 1 ? 's' : ''}</strong><p>${size} · pronto para análise</p><small>O conteúdo ainda não foi enviado nem instalado.</small>`;
  $('#analyze-btn').disabled = false;
}

$('#analyze-btn').addEventListener('click', () => {
  $('#analyze-btn').innerHTML = 'Analisando…';
  setTimeout(() => {
    $('#analyze-btn').innerHTML = 'Análise concluída ✓';
    showToast('Estrutura compatível encontrada');
  }, 900);
});

$('#settings-form').addEventListener('change', event => {
  if (!event.target.matches('input, select, textarea')) return;
  $('.saved-state').textContent = '● Alterações pendentes';
  $('.saved-state').style.color = '#e1b65a';
});
