# Capivara DSM 2.0.15

## Diagnóstico de instalação remota do Agent

- Corrige o diagnóstico do deploy remoto Linux para preservar a causa real enviada em `stderr`.
- Prioriza marcadores `CAPIVARA_BOOTSTRAP_ERROR` e `[Capivara Agent][ERRO]` sobre mensagens de progresso do `stdout`.
- Impede que uma linha de sucesso como `Pacote validado por SHA-256` seja exibida como causa de falha do bootstrap.
- Mantém o pairing token fora de mensagens, argumentos e diagnósticos.
- Adiciona regressão específica para a prioridade dos diagnósticos do bootstrap remoto.
- Integra o novo teste ao workflow `Agent SSH Deploy`.

Esta release é preparada para diagnosticar corretamente a falha observada após a validação SHA-256 durante a instalação remota do Agent Linux.
