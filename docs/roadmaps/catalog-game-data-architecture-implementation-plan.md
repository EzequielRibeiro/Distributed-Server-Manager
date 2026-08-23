# Cronograma — Catálogo / Game Data / Runtime / Recursos

Status desta fundação: iniciado em 2026-08-23.

| Etapa | Entrega | Estado | Critério de conclusão |
|---|---|---|---|
| 1 | Auditoria e modelo de domínio | Concluída | Componentes reutilizáveis e fronteiras Catálogo/Contrato/Instância documentados |
| 2 | Remodelagem da página Catálogo | Concluída nesta fundação | Interface não seleciona nem administra instância e expõe áreas de Game Data, Parâmetros, Configuração, Recursos, Conteúdo, Agents e Versões |
| 3 | Inventário e instalação de game-data | Base existente / integração em andamento | Admin consegue disparar instalação e consultar jobs por Agent usando a plataforma distribuída existente |
| 4 | Gerenciador seguro de arquivos de game-data | Planejada | list/read/create/write/rename/upload/delete confinados à raiz autorizada, RBAC e auditoria |
| 5 | Parâmetros de runtime e templates | Planejada | RuntimeDefinition suporta startup/vars/shutdown/working directory e UI persiste definição validada |
| 6 | Perfis de recursos | Fundação concluída | Schema e perfis de catálogo existem; próxima entrega aplica persistência/edição pela UI |
| 7 | Contratos × perfis permitidos | Planejada | contrato lista profiles permitidos e criação de instância rejeita perfil fora do contrato |
| 8 | Placement + instalação sob demanda | Planejada | placement considera recursos; ausência de game-data cria job e provisionamento aguarda conclusão |
| 9 | Integridade, auditoria e versionamento | Planejada | alterações de game-data geram estado MODIFIED, eventos, verify/repair/revert |
| 10 | E2E e rollout | Planejada | fluxo Catálogo→Agent→Contrato→Placement→Instância validado em Linux/Windows conforme suporte do runtime |

## Ordem técnica

As etapas 4 e 5 devem preceder a edição administrativa completa. A etapa 7 deve preceder a exposição dos perfis ao cliente. A etapa 8 é o ponto em que a arquitetura passa a controlar efetivamente capacidade e instalação sob demanda no ciclo completo de provisionamento.

## Gate de segurança

Nenhuma operação de edição de game-data deve usar caminhos arbitrários enviados pelo navegador. A raiz é derivada da definição de runtime validada e do Agent selecionado. Escritas exigem autorização administrativa, containment de caminho e auditoria.
