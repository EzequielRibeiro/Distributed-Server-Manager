# Capivara DSM 2.0.19

## Windows Agent

- adiciona protocolo administrativo tipado de desinstalação remota;
- adiciona modos `preserve-data` e `purge`;
- adiciona confirmação exata pelo Agent ID;
- adiciona execução independente por Scheduled Task como SYSTEM;
- adiciona resultado terminal autenticado `completed` / `failed`;
- adiciona limpeza do launcher, lock, snapshot de credencial e Scheduled Task auxiliar;
- preserva `instances` e `backups` no modo `preserve-data`;
- separa desinstalação remota da remoção somente no Controller.

## Controller / Dashboard

- adiciona estado e entrega do fluxo de desinstalação remota;
- adiciona `/api/agent/uninstall/result`;
- atualiza Danger Zone para distinguir uninstall remoto de force-remove Controller-only.

## Validation

- 29 testes de uninstall aprovados;
- validação E2E parcial em Windows Server;
- validação real de autolimpeza da Scheduled Task e do PowerShell staged.
