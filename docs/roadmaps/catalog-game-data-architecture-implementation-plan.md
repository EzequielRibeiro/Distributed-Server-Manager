# Cronograma — Catálogo / Game Data / Runtime / Recursos

Status desta fundação: iniciado em 2026-08-23.

| Etapa | Entrega | Estado | Critério de conclusão |
|---|---|---|---|
| 1 | Auditoria e modelo de domínio | Concluída | Componentes reutilizáveis e fronteiras Catálogo/Contrato/Instância documentados |
| 2 | Remodelagem da página Catálogo | Concluída | Interface não seleciona nem administra instância e expõe áreas de Game Data, Parâmetros, Configuração, Recursos, Conteúdo, Agents e Versões |
| 3 | Inventário e instalação de game-data | Concluída | Admin dispara install/update/verify, consulta jobs e vê por Agent os ambientes já confirmados pelos resultados do runtime distribuído |
| 4 | Gerenciador seguro de arquivos de game-data | Concluída (Linux Agent) | list/read/create/write/mkdir/rename/upload/delete confinados à raiz autorizada, somente admin e registrados como jobs distribuídos |
| 5 | Parâmetros de runtime e templates | Próxima | RuntimeDefinition suporta startup/vars/shutdown/working directory e UI persiste definição validada |
| 6 | Perfis de recursos | Fundação concluída | Schema e perfis de catálogo existem; próxima entrega aplica persistência/edição pela UI |
| 7 | Contratos × perfis permitidos | Planejada | contrato lista profiles permitidos e criação de instância rejeita perfil fora do contrato |
| 8 | Placement + instalação sob demanda | Planejada | placement considera recursos; ausência de game-data cria job e provisionamento aguarda conclusão |
| 9 | Integridade, auditoria e versionamento | Planejada | alterações de game-data geram estado MODIFIED, eventos, verify/repair/revert |
| 10 | E2E e rollout | Planejada | fluxo Catálogo→Agent→Contrato→Placement→Instância validado em Linux/Windows conforme suporte do runtime |

## Etapa 3 — resultado

O Controller possui a fila persistente de jobs de game-data e recebe do Agent o resultado real de install/update/verify. A Dashboard consolida esses resultados em `/api/agents/game-data/inventory`, permitindo selecionar um Agent e identificar se o ambiente está instalado, versão conhecida, caminho reportado, último estado e jobs ativos.

## Etapa 4 — resultado

A mesma fila distribuída passou a transportar operações administrativas de arquivos. O navegador nunca fornece uma raiz absoluta: Controller resolve novamente o RuntimeDefinition, envia apenas caminho relativo e o Agent deriva localmente a raiz autorizada do game-data. O executor rejeita caminhos absolutos, `..`, escapes por symlink, edição textual acima de 1 MiB e upload acima de 32 MiB.

Operações suportadas no Linux Agent: listar diretório, ler texto UTF-8, criar/sobrescrever arquivo, criar pasta, renomear, excluir e upload binário. Somente administradores podem enfileirar essas ações. Cada mutação permanece identificável por `job_id`, Agent, runtime, usuário solicitante, ação e timestamps na persistência de `agent_game_data_jobs`.

A Dashboard expõe navegador de arquivos e editor textual na aba **Game Data** sem acesso à árvore privada das instâncias. Paridade do protocolo de arquivos no Agent Windows será coberta pelo rollout multiplataforma da etapa 10 antes de declarar suporte Windows para edição remota de game-data.

## Ordem técnica

A etapa 5 é agora a próxima entrega. A etapa 7 deve preceder a exposição dos perfis ao cliente. A etapa 8 é o ponto em que a arquitetura passa a controlar efetivamente capacidade e instalação sob demanda no ciclo completo de provisionamento.

## Gate de segurança

Nenhuma operação de edição de game-data usa caminhos absolutos enviados pelo navegador. A raiz é derivada da seleção de runtime validada e do Agent. Escritas exigem administrador, containment de caminho no Agent e registro persistente da operação distribuída.
