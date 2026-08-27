# Capivara DSM 2.0.9

Esta release consolida o estado atual do Capivara DSM após o fechamento das pendências P1–P8 e das correções pré-release adicionais validadas antes da retomada da P9.

## Principais entregas

- cleanup seguro pós-migração de Storage Pool;
- HTTPS/TLS completo para o Controller e comunicação externa;
- paridade ampliada do Agent Windows, incluindo GUI opcional;
- validação E2E real de comunicação externa Controller ↔ Agent com DNS, HTTPS, NAT, queda e reconexão;
- placement geográfico e por capacidade/latência;
- observabilidade administrativa consolidada;
- instalação remota Linux/Windows e fluxos administrativos de Agent;
- identidade pública do Agent com `public_hostname` e `public_ipv4`;
- configuração da rede pública durante os wizards de instalação da Dashboard e também após a instalação;
- validação DNS com fallback automático para IPv4 público;
- endereço de conexão do servidor de jogo exposto ao Customer como `host:porta`;
- exposição da rede pública na GUI opcional do Agent Windows;
- melhorias no Customer Workspace, Customer health, self-service, atividade/auditoria e operações distribuídas.

## Correções administrativas

- `AgentAdminRepository.detail()` usa o campo oficial `issued_at` de `agent_credentials`, eliminando o erro PostgreSQL causado pela referência ao campo inexistente `created_at`.
- A tela de detalhes administrativos do Agent volta a consultar normalmente os dados persistidos no Controller.

## Segurança e conectividade

- Controller TLS permanece obrigatório nos cenários externos recomendados.
- O endereço operacional do Agent continua separado do endpoint público entregue aos jogadores.
- O hostname público somente é priorizado quando a resolução DNS é válida; caso contrário, o Customer recebe o IPv4 público configurado.
- A configuração de rede pública não exige reinstalação do Agent quando DNS ou IP mudarem.

## Bancos de dados

A readiness cobre SQLite, PostgreSQL, MySQL e MariaDB. O baseline PostgreSQL isolado permanece um gate obrigatório da release.

## Agents

Os pacotes Linux e Windows são validados pelo CI antes da publicação. Windows Agent parity, SSH deploy, instalação remota pela Dashboard, Agent Local CLI, runtime e rede pública são gates explícitos da v2.0.9.

## Validação de release

A P9 exige os gates atuais de runtime, instalação, Customer, TLS, rede pública, observabilidade, schemas, Phase 22 e E2E distribuído antes da criação da tag.

A readiness não publica uma release automaticamente. A publicação oficial somente ocorre depois da integração da preparação e da criação explícita da tag SemVer correspondente.

## Atualização

Atualize a partir da v2.0.8 usando o fluxo oficial de update do Capivara. Após a publicação, o updater deverá detectar a v2.0.9 como versão estável mais recente.

## Pacotes

Use somente artefatos oficiais da GitHub Release e valide SHA-256/manifest. A release deve conter o pacote principal `capivara-dsm-2.0.9.tar.gz` e os pacotes oficiais dos Agents Linux e Windows.
