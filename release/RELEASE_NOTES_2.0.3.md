# Capivara DSM 2.0.3

Release corretiva para observabilidade, logs remotos e navegação da Dashboard.

## Correções

- restaura a telemetria de CPU e RAM para Agents sem instâncias;
- transporta logs recentes do Agent pelo heartbeat autenticado;
- adiciona seleção real de Agent ao visualizador de logs;
- registra as rotas da página `servers-v2` e seus assets;
- corrige a descoberta do caminho absoluto de `true` no `cap agent ssh-prepare`;
- adiciona fallback portátil à coleta de carga do sistema.
