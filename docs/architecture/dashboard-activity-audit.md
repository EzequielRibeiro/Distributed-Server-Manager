# Dashboard Activity Audit

A Dashboard do Capivara mantém uma trilha de auditoria persistente e consultável de atividades humanas. A consulta é exclusiva do papel `admin`.

## Objetivo

Responder, de forma objetiva, às perguntas:

- quem acessou o sistema;
- quando entrou e quando saiu;
- quais páginas consultou;
- quais APIs/ações executou;
- qual foi o resultado da ação;
- de qual endereço IP e navegador a ação partiu;
- quais ações pertencem à mesma sessão;
- quais ações um usuário realizou dentro de um período.

A trilha é persistida em `dashboard_activity_log`. O `audit_log` histórico permanece disponível para compatibilidade com auditorias específicas de instância, mas não é a fonte da auditoria global da Dashboard.

## Segurança e privacidade

O registro global nunca persiste:

- senha;
- hash de senha;
- cabeçalho `Authorization`;
- cookie de autenticação;
- token de sessão;
- token de API;
- corpo bruto da requisição.

`session_id` é um identificador de correlação obtido de um hash SHA-256 truncado do token de sessão. O token original nunca é armazenado.

A falha na gravação da auditoria não transforma uma operação funcional bem-sucedida em falha para o usuário; erros de infraestrutura de auditoria devem ser detectados pela observabilidade do Controller.

## Modelo persistido

Cada atividade contém, quando aplicável:

- `event_id` — identificador UUID do evento;
- `username` — usuário responsável;
- `role` — papel no momento da ação;
- `session_id` — correlação segura da sessão;
- `activity` — nome da atividade;
- `category` — domínio funcional;
- `result` — `success`, `denied` ou `error`;
- `method` — método HTTP;
- `path` — rota acessada;
- `status_code` — resultado HTTP;
- `remote_address` — IP de origem;
- `user_agent` — navegador/cliente;
- `target_type` e `target_id` — reservados para enriquecimento semântico do recurso afetado;
- `details_json` — detalhes estruturados não sensíveis;
- `created_at` — timestamp do banco.

## Mapeamento das funcionalidades

### Autenticação e sessão — `authentication`

- login bem-sucedido;
- tentativa de login recusada;
- logout explícito;
- troca obrigatória de senha no primeiro acesso;
- operações futuras de sessão/autenticação.

Atividades canônicas: `LOGIN`, `LOGOUT`; demais rotas usam o nome derivado do método e da rota até receberem um nome semântico específico.

### Navegação — `navigation`

- abertura de páginas HTML autenticadas;
- entrada em Dashboard, páginas administrativas e páginas de Customer.

Atividade canônica: `PAGE_VIEW`.

### Usuários do sistema — `system_users`

- criação de Admin/Controller/Operator;
- edição de perfil, vínculo e dados funcionais;
- ativação/desativação;
- exclusão;
- tentativa bloqueada envolvendo último Admin/último Admin ativo;
- renovação da senha temporária.

### Clientes — `customers`

- consulta de Customer;
- criação de Customer;
- consulta de dados;
- membros e convites;
- identidades/login do Customer;
- Billing vinculado ao Customer;
- criação e administração de contratos.

### Catálogo e perfis de jogo — `catalog`

- consulta de catálogo;
- criação de resource profile;
- edição de resource profile;
- exclusão de resource profile;
- definição do perfil padrão;
- alterações de runtime policy e demais políticas do catálogo.

### Agents — `agents`

- consulta e administração de Agent;
- cadastro/pareamento;
- localização;
- portas;
- atualização;
- game-data;
- ações remotas/terminal quando expostas à Dashboard.

### Instâncias — `instances`

- criação/provisionamento;
- start;
- stop;
- restart;
- status solicitado pelo usuário;
- reinstall;
- delete;
- alteração de configuração;
- arquivos da instância;
- demais ações do ciclo de vida.

### Conteúdo — `content`

- instalação, remoção e verificação de conteúdo;
- mods/plugins e operações equivalentes expostas pela Dashboard.

### Backup — `backup`

- criação;
- restauração;
- exclusão;
- consulta/download quando iniciados pelo usuário.

### Infraestrutura — `infrastructure`

- Regions;
- Datacenters;
- Placement;
- configuração de infraestrutura;
- ações administrativas relacionadas à topologia.

### Automação — `automation`

- criação/alteração/execução de automações.

### Broadcast — `broadcast`

- envio e administração de mensagens broadcast.

### Eventos — `events`

- ações humanas na plataforma de eventos e timeline.

### Configuração — `configuration`

- alterações de configuração do Controller/Dashboard;
- administração de credenciais/tokens quando aplicável.

## Eventos que não pertencem à auditoria humana

A trilha administrativa não deve armazenar polling ou tráfego periódico de máquina a máquina. Isso evita crescimento artificial do banco e mantém a consulta orientada à atividade do usuário.

Exclusões iniciais:

- `/ping`;
- `/health`;
- `/api/controller/telemetry`;
- `/api/realtime/events`.

Heartbeat de Agent, métricas, observabilidade contínua e eventos internos continuam nas suas plataformas próprias de observabilidade/eventos.

## Cobertura automática

`dashboard_activity_http.py` é instalado como a camada HTTP mais externa de `server_part17.py`.

Isso garante que:

1. páginas autenticadas gerem `PAGE_VIEW`;
2. ações humanas em `/api/*` sejam registradas automaticamente;
3. respostas 401/403 também possam aparecer como atividade recusada quando há uma identidade tentada/conhecida;
4. novas rotas adicionadas abaixo da composição final recebam cobertura básica sem exigirem um `write_audit()` manual;
5. ações importantes possam ser enriquecidas posteriormente com `target_type`, `target_id` e detalhes sem alterar a estrutura da tabela.

## Consulta administrativa

Página: `/activity-log.html`

API: `/api/admin/activity-log`

Filtros:

- data/hora inicial;
- data/hora final;
- usuário;
- categoria;
- atividade;
- resultado;
- limite de registros.

A lista de usuários, categorias e atividades disponíveis é fornecida por `/api/admin/activity-log/options`.

Todos esses endpoints são exclusivos de `admin`; esconder o item de menu não é considerado proteção de segurança.

## Retenção

A persistência no banco é intencional para permitir investigação histórica. Política automática de expurgo/arquivamento deve ser configurável em uma etapa própria, por exemplo 90/180/365 dias ou retenção externa, e nunca deve apagar registros silenciosamente sem uma política administrativa explícita.
