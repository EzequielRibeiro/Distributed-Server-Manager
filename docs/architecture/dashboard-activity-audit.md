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

O registro global nunca persiste senha, hash de senha, cabeçalho `Authorization`, cookie de autenticação, token de sessão, token de API ou corpo bruto da requisição.

`session_id` é um identificador de correlação obtido de um hash SHA-256 truncado do token de sessão. O token original nunca é armazenado.

A falha na gravação da auditoria não transforma uma operação funcional bem-sucedida em falha para o usuário; erros de infraestrutura de auditoria devem ser detectados pela observabilidade do Controller.

## Modelo persistido

Cada atividade contém, quando aplicável: `event_id`, `username`, `role`, `session_id`, `activity`, `category`, `result`, `method`, `path`, `status_code`, `remote_address`, `user_agent`, `target_type`, `target_id`, `details_json` e `created_at`.

`target_type`, `target_id` e `details_json` permitem enriquecimento semântico futuro sem alterar a estrutura da tabela.

## Ciclo da sessão

O login gera `LOGIN`, cria a sessão normal do Controller e correlaciona o evento ao identificador seguro derivado da sessão. Navegações HTML são identificadas pelo cookie de sessão; APIs também podem usar a autenticação Basic existente durante a transição do modelo de autenticação.

O botão **Sair** chama `/api/auth/logout`, revoga a sessão no servidor, expira o cookie e gera `LOGOUT`. O token real da sessão nunca é armazenado na auditoria.

Fechar o navegador, perder a rede ou deixar a sessão expirar não deve ser falsamente registrado como `LOGOUT`, pois não houve essa ação do usuário. Uma futura persistência explícita do ciclo de vida das sessões poderá produzir `SESSION_EXPIRED` separadamente.

## Mapeamento das funcionalidades

- `authentication`: login, tentativa recusada, logout, troca de senha e demais operações de autenticação/sessão.
- `navigation`: abertura de páginas HTML autenticadas (`PAGE_VIEW`).
- `system_users`: criação, edição, ativação, desativação, exclusão e proteção de contas Admin/Controller/Operator.
- `customers`: consulta/criação de Customer, membros, convites, identidades, Billing e contratos.
- `catalog`: catálogo, resource profiles, perfil padrão e runtime policies.
- `agents`: cadastro, pareamento, localização, portas, atualização, game-data e ações remotas expostas pela Dashboard.
- `instances`: criação/provisionamento, start, stop, restart, reinstall, delete, configurações e arquivos.
- `content`: mods/plugins e instalação, remoção ou verificação de conteúdo.
- `backup`: criação, restauração, exclusão, consulta e downloads iniciados pelo usuário.
- `infrastructure`: Regions, Datacenters, Placement e topologia.
- `automation`: criação, alteração e execução de automações.
- `broadcast`: envio e administração de mensagens broadcast.
- `events`: ações humanas sobre eventos/timeline.
- `configuration`: alterações de configuração e administração de credenciais/tokens quando aplicável.

Atividades canônicas iniciais são `LOGIN`, `LOGOUT` e `PAGE_VIEW`; demais APIs recebem um identificador determinístico derivado do método e da rota, permitindo filtragem imediatamente e nomes semânticos adicionais no futuro.

## Eventos que não pertencem à auditoria humana

A trilha administrativa não deve armazenar polling ou tráfego periódico de máquina a máquina. Isso evita crescimento artificial do banco e mantém a consulta orientada à atividade do usuário.

Exclusões iniciais: `/ping`, `/health`, `/api/controller/telemetry` e `/api/realtime/events`.

Heartbeat de Agent, métricas, observabilidade contínua e eventos internos continuam nas suas plataformas próprias de observabilidade/eventos.

## Cobertura automática

`dashboard_activity_http.py` é instalado como a camada HTTP mais externa de `server_part17.py`. Assim, páginas autenticadas e ações humanas em `/api/*` recebem cobertura básica automaticamente, inclusive respostas recusadas, sem exigir que cada nova funcionalidade lembre de chamar um `write_audit()`.

Ações importantes podem ser enriquecidas posteriormente com recurso-alvo e detalhes não sensíveis.

## Consulta administrativa

Página: `/activity-log.html`

APIs:

- `/api/admin/activity-log`
- `/api/admin/activity-log/options`

Filtros disponíveis: data/hora inicial, data/hora final, usuário, categoria, atividade, resultado e limite de registros. Isso permite, por exemplo, consultar somente `LOGIN` de um usuário dentro de um período ou todas as ações daquele usuário em uma sessão de investigação.

Todos esses endpoints são exclusivos de `admin`; esconder o item de menu não é considerado proteção de segurança.

## Retenção

A persistência no banco é intencional para permitir investigação histórica. Política automática de expurgo/arquivamento deve ser configurável em uma etapa própria, por exemplo 90/180/365 dias ou retenção externa, e nunca deve apagar registros silenciosamente sem uma política administrativa explícita.
