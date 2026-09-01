# Capivara DSM 2.0.20

## Windows Agent

- Corrige a instalação do runtime Windows para preservar subdiretórios.
- Inclui corretamente `runtime/adapters` no Agent instalado.
- Adiciona validação dos arquivos obrigatórios dos adapters no instalador.
- Corrige a falha de instalação que resultava em `ModuleNotFoundError: No module named 'adapters'`.

## Agent deployment

- Mantém compatibilidade com instalação remota via OpenSSH.
- Esta release substitui a v2.0.19 para novas instalações do Agent Windows.
