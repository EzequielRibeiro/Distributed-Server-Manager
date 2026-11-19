# Capivara DSM 2.0.133-rc.4 — Homologação isolada de DayZ (19/11/2026)

**Canal:** candidata **local e não publicada**. Esta branch não é tag, não é uma release GitHub e **não autoriza atualização automática do Horizon**.

## Escopo da candidata

- Base: merge da PR #1086 (commit f26b618b96d6d87057e85485718624d380767c6d), com 35/35 workflows da PR aprovados.
- PR #1085 / issue #1084: habilitação administrativa auditada de Mods e Workshop para contratos DayZ existentes (incorporada anteriormente).
- PR #1086: Mods e Workshop disponíveis por padrão no produto DayZ standard, inclusive em contratos legados com flags persistidas pela antiga distinção comercial; não altera perfis de CPU/RAM/disco, autorização do usuário ou limites do runtime.
- Interface DayZ: a aba Mundo & Mapa permanece visível diante de erro HTTP (inclusive 404), exibe mensagem e botão para repetir consulta; cache bust `customer-dayz.js?v=20`.
- Não instala mods automaticamente, não troca mapa ativo, não reinicia jogo e não modifica os arquivos das instâncias.

## Homologação ainda necessária

1. Construir pacote em checkout isolado com `release/build_release.sh HEAD dist`, verificar manifest e SHA-256, validar CI/preflight.
2. No Horizon, **antes de instalar**, checar backup, espaço, serviços e instâncias ativas. O atualizador atual para e restaura jogos ativos; precisa de janela de manutenção autorizada para DayZ 001.
3. Após instalação controlada, conferir no Chrome Android a aba Mundo & Mapa no DayZ 002; se houver erro, registrar o HTTP e diagnosticar API.
4. Testar fluxo normal do cliente de cadastro Namalsk com descoberta `regular.namalsk` e `hardcore.namalsk` no Agent VPS sem trocar missão ou iniciar/reiniciar o jogo sem aprovação.

**Bloqueios de release estável permanecem:** validação real do Agent VPS e demais gates de release em aberto. Não publicar tag, não modificar RELEASE_TRIGGER, não promover stable e não fechar issue #1084 automaticamente.
