# Catálogo por jogo

Este diretório inicia a consolidação dos arquivos declarativos de cada jogo em um namespace canônico.

A estrutura atual de `catalog/v2/runtimes/` e `catalog/v2/content/` continua ativa durante a migração. Nenhuma API deve assumir que os manifests já foram movidos para este diretório.

## Estrutura pretendida

```text
catalog/v2/games/
└── <game>/
    ├── game.json
    ├── runtimes/
    ├── content/
    ├── network.json
    └── capabilities.json
```

Nem todo jogo precisa de todos os arquivos. O objetivo é que os dados que descrevem um jogo tenham um domínio único e identificável, enquanto mecanismos compartilhados permaneçam em `catalog/v2/providers/` e contratos compartilhados em `catalog/v2/schemas/`.

## Jogos atualmente identificados no catálogo

- `arma3`
- `dayz`
- `luanti`
- `mindustry`
- `minecraft`
- `rust`

Nesta etapa esses nomes ainda correspondem aos diretórios existentes em `catalog/v2/runtimes/`; eles serão migrados gradualmente após a auditoria das referências.

## O que não pertence aqui

Providers reutilizáveis não devem ser copiados para cada jogo. Exemplos:

- Steam;
- HTTP / HTTP Archive;
- GitHub Releases;
- Modrinth;
- providers customizados genéricos.

O código de operação do processo também não deve ser duplicado aqui. Adaptadores, launchers e integrações operacionais continuam em `games/<game>/`.

Consulte `docs/architecture/game-directory-layout.md` para o plano de migração e regras de classificação.
