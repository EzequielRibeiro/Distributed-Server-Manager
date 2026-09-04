# Capivara DSM v2.0.22

Esta release consolida o maior conjunto de mudanças desde a v2.0.21, com foco em catálogo multi-jogo, contratos canônicos de runtime, Placement estruturado, políticas de recursos e parâmetros, agentes Linux/Windows e networking público.

## Destaques

- Consolida contratos canônicos de Runtime/Engine, Installation Strategy, Configuration Precedence e Canonical Parameter Policy.
- Expande o Catalog v2 com novos runtimes e gates de readiness/paridade entre Catalog e Agents.
- Adiciona suporte e integração para novos servidores e engines, incluindo Project Zomboid, Counter-Strike 2, Garry's Mod, Left 4 Dead 2, Palworld, Satisfactory, Team Fortress 2, 7 Days to Die, Factorio, Arma Reforger, The Isle e múltiplos runtimes Minecraft.
- Adiciona runtimes Minecraft Forge, NeoForge, Folia, Purpur, Quilt, SpongeVanilla e Youer.
- Introduz políticas efetivas de recursos, capabilities estruturadas e melhorias no Placement geográfico/operacional.
- Adiciona runtime secrets com persistência, transporte e integração Controller↔Agent.
- Evolui a plataforma universal de conteúdo, incluindo Steam Workshop, adapters de ativação e monitoramento de atualizações.
- Adiciona plataforma universal de atualização de servidores e inventário de versões.
- Reforça lifecycle dos Agents, incluindo remoção administrativa segura, validação destrutiva de alvo, relink/recovery e atualização com preservação de identidade.
- Reforça paridade Linux/Windows para instalação, runtime, conteúdo, telemetria e update flows.
- Adiciona suporte de rede pública NAT-aware com IPv6, nat_scope e mapeamento entre bind_port e public_port.
- Melhora a experiência do cliente em seleção de região/placement e evita travamentos quando não existem Agents elegíveis.
- Reduz vazamentos do CLI legado `dsm` em superfícies públicas, mantendo compatibilidade interna onde necessária.

## Catálogo e readiness

- Adiciona support matrix canônica e auditoria de readiness de runtime.
- Adiciona snapshot Steam Top 25 de 2026-09-03.
- Mantém como `deferred` apenas runtimes cuja implementação específica ainda não atende ao contrato técnico atual.
- Amplia CI dedicado para arquitetura do catálogo, paridade Catalog↔Agent e readiness por runtime.

## Rede e exposição pública

- Suporte a `public_ipv4`, `public_ipv6`, `nat_scope` e `port_mappings`.
- Mapeamento explícito de porta interna para porta pública por protocolo.
- Validação de colisões de porta pública dentro do mesmo escopo NAT.
- Endpoint do cliente passa a anunciar a porta pública efetiva quando configurada.

## Agents

- Linux Agent: melhorias de capacidades, runtime policy, configuração, conteúdo, updates e uninstall seguro.
- Windows Agent: evolução de capabilities, runtime policy, conteúdo, game data e launcher/service behavior.
- Novos testes de integridade do lifecycle, preservação de identidade e segurança de atualização/desinstalação.

## Qualidade

- Novos workflows de CI para readiness, lifecycle, placement, resource policy, configuration precedence, runtime secrets, content providers e runtimes específicos.
- Ampliação significativa da cobertura automatizada antes da publicação.

Comparação de base: `v2.0.21...v2.0.22`.
