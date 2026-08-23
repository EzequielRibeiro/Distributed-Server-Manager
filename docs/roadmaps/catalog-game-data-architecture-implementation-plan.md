# Cronograma — Catálogo / Game Data / Runtime / Recursos

Ciclo iniciado e concluído em 2026-08-23.

| Etapa | Entrega | Estado | Critério de conclusão |
|---|---|---|---|
| 1 | Auditoria e modelo de domínio | ✅ Concluída | Componentes reutilizáveis e fronteiras Catálogo/Contrato/Instância documentados |
| 2 | Remodelagem da página Catálogo | ✅ Concluída | Interface não seleciona nem administra instância e expõe áreas de Game Data, Parâmetros, Configuração, Recursos, Conteúdo, Agents e Versões |
| 3 | Inventário e instalação de game-data | ✅ Concluída | Admin dispara install/update/verify, consulta jobs e vê por Agent os ambientes confirmados pelo runtime distribuído |
| 4 | Gerenciador seguro de arquivos de game-data | ✅ Concluída | list/read/create/write/mkdir/rename/upload/delete confinados à raiz autorizada e transportados como jobs administrativos |
| 5 | Parâmetros de runtime e templates | ✅ Concluída | `CatalogRuntimePolicy`, API e UI persistem executable, argv, environment, vars, working directory, shutdown, timeouts e templates |
| 6 | Configuração materializada pelo Agent | ✅ Concluída | Runtime Policy é aplicada ao RuntimeSpec e templates são materializados dentro da árvore privada da instância |
| 7 | Manutenção do Game Data | ✅ Concluída | `install/update/verify/repair`, inventário de integridade e histórico de jobs disponíveis |
| 8 | Integração com provisionamento | ✅ Concluída | Controller resolve RuntimeSelection/policy/perfil e provisionamento usa `ensure` para reutilizar base íntegra ou instalar sob demanda |
| 9 | Inventário, consistência e recuperação | ✅ Concluída | estado persistente + integrity + reconcile classificam bases ausentes/degradadas/inseguras e diretórios órfãos |
| 10 | Paridade multiplataforma e gate final | ✅ Concluída | Linux e Windows possuem Game Data File Manager, integrity, ensure/repair e aplicação da Runtime Policy; gate dedicado cobre o contrato |

## Resultado arquitetural

```text
Catálogo
  ├── RuntimeDefinition
  ├── CatalogRuntimePolicy
  ├── Templates
  └── GameResourceProfiles
          │
          ▼
Cliente → Contrato → Criar Instância
          │
          ▼
Placement → Agent
          │
          ▼
ensure game-data
  ├── íntegro → reutiliza
  └── ausente/degradado → instala/repara
          │
          ▼
RuntimeSpec + recursos + portas
          │
          ▼
materialização + templates
          │
          ▼
Instance Runtime
```

## Etapas 5–6 — Startup e configuração

A política editável não altera o arquivo declarativo original do catálogo. Overrides ficam em `config/catalog-runtime/<runtime_id>.json`, sobrevivem a reinstalações e são validados antes da gravação. O Agent resolve placeholders no momento da materialização, sem depender de shell arbitrário.

Templates são caminhos relativos e não podem conter traversal. No Linux, o helper privilegiado escreve os arquivos depois da criação da árvore da instância; portanto a política não transforma `game-data` em configuração privada do cliente.

## Etapas 7–9 — Manutenção e recuperação

`verify` gera metadados de integridade e confirma a presença do executável esperado. `repair` reaplica o provider oficial. `ensure` é a operação usada no provisionamento: evita reinstalação quando a base já está íntegra.

A reconciliação usa o estado persistente do Agent e o filesystem real para classificar conteúdo como `ok`, `missing`, `empty`, `degraded`, `unsafe` ou `orphaned`. Jobs finais permanecem arquivados após a remoção de payloads transitórios.

## Etapa 10 — Paridade

O protocolo de arquivos seguro e o inventário de integridade existem em Linux e Windows. O build Linux lista explicitamente os novos módulos; o build Windows inclui automaticamente os módulos Python do runtime.

## Gate de segurança

Nenhuma operação de edição de game-data usa uma raiz absoluta fornecida pelo navegador. A raiz é derivada da RuntimeSelection no Agent. Paths absolutos, `..` e escapes por symlink são rejeitados. Escritas exigem administrador no Controller. Runtime Policy e perfis de recursos são validados novamente antes do provisionamento.

## Gate de qualidade

O workflow `.github/workflows/catalog-architecture.yml` executa compilação Python, validação JavaScript, testes das etapas 5–10 e contratos de pacote Linux/Windows. A suíte principal continua responsável pelo gate global, incluindo Catalog v2 e Fase 22 E2E.
