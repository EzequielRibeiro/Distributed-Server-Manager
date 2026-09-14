# C4 — Universal Content Platform

## Objetivo

C4 transforma conteúdo instalável em desired state do Control Plane. O Controller não executa shell remoto nem conhece regras específicas de jogos; ele persiste uma atribuição declarativa e o Agent reconcilia instalação e ativação localmente.

O termo **Universal** inclui explicitamente o ecossistema Minecraft. O mesmo plano deve administrar conteúdo de jogos Steam, Minecraft e futuros runtimes sem criar um segundo sistema de mods/plugins no Dashboard, Controller ou File Manager.

Invariante arquitetural:

```text
Provider / External Upload
          |
          v
ContentAssignment / ContentRevision
          |
          v
Agent runtime/content adapter
          |
          v
materializer / activation projection
          |
          v
restart + readiness
```

Providers resolvem origem e versões. O UCP mantém estado, revisão, segurança e intenção. O Agent conhece a projeção específica do runtime.

## Contrato

`CapivaraContentAssignment` identifica `agent_id`, `instance_id`, `content_id`, jogo, tipo, versão, provider, target, artifact, dependências, conflitos, desired state, activation state/order e checksum. `installed` solicita presença; `absent` solicita remoção apenas do target gerenciado. Conteúdo instalado pode permanecer `disabled`: continua presente, mas não participa da projeção ativa.

Targets padrão são isolados por conteúdo (`mods/<content-id>`, `plugins/<content-id>`, etc.) para que uma remoção não apague conteúdo vizinho.

A capacidade de conteúdo pertence ao `RuntimeDefinition`. Controller e Dashboard não podem inferir que todo Minecraft aceita qualquer tipo de conteúdo.

## Fluxo distribuído

```text
Catalog / Customer / Admin
          |
          v
Controller content_assignments
          |
          | heartbeat response
          v
Agent content_client
          |
          +-- validate ownership
          +-- resolve confined target
          +-- download/copy
          +-- verify checksum
          +-- safe extract
          +-- atomic replace
          +-- build deterministic activation snapshot
          +-- project through runtime adapter
          |
          v
instance managed content/runtime projection
          |
          | next heartbeat: content_state ACK
          v
Controller agent_content_state
```

O Controller retransmite uma revisão até receber `applied_revision + applied_checksum` com `status=applied`. O modelo é at-least-once e idempotente.

## Estado do roadmap

### U1–U4 — concluídas

A fundação do UCP, contrato distribuído, Customer Content e Steam Workshop permanecem concluídos. O rebaseline Minecraft não reabre essas fases.

### U5 — Universal Content Activation Layer — concluída

U5 foi concluída no PR #466 e permanece a camada genérica de ativação:

- snapshots determinísticos Linux/Windows;
- `activation_state` e `activation_order` no runtime real;
- conteúdo `disabled` instalado porém não ativo;
- materialização antes de start/reconcile;
- restart/readiness após mudança;
- rollback da projeção anterior em falha;
- paridade Linux/Windows;
- lógica específica de jogo mantida no Agent.

Os primeiros adapters reais cobrem DayZ e Project Zomboid. Isso não limita o escopo universal.

### U5-M — Minecraft Activation Adapters — concluída

U5-M estende a U5 já concluída para os runtimes Minecraft modificáveis, sem duplicar o mecanismo central.

Matriz inicial de capacidades:

| Runtime family | Mods | Plugins | Datapacks | Modpacks |
| --- | --- | --- | --- | --- |
| Vanilla | não | não | sim | não |
| Paper / Purpur / Folia | não | sim | sim | conforme contrato do pack |
| Fabric | sim | não | sim | sim |
| Forge | sim | não | sim | sim |
| NeoForge | sim | não | sim | sim |
| Quilt | sim | não | sim | sim |
| Sponge | conforme RuntimeDefinition | conforme RuntimeDefinition | sim | conforme RuntimeDefinition |
| Arclight / Youer | sim | sim | sim | sim |

A tabela acima é diretriz de arquitetura; a fonte de verdade executável deve ser o Catalog/`RuntimeDefinition` de cada runtime.

Requisitos U5-M:

- Paper/Purpur/Folia projetam conteúdo gerenciado em `plugins/`;
- Fabric/Forge/NeoForge/Quilt projetam conteúdo gerenciado em `mods/`;
- runtimes híbridos declaram explicitamente `mods + plugins`;
- combinações não suportadas falham fechadas;
- enable/disable não exige redownload;
- projeção e checksum são determinísticos;
- rollback restaura a projeção anterior;
- Linux e Windows possuem o mesmo contrato semântico;
- Controller/Dashboard não contêm `if game == minecraft` para ativação.

Tracker: #489.

### U6 — External Upload — concluída

U6 continua genérica e reutiliza o Artifact Transfer Plane. Upload não escreve diretamente em `mods/`, `plugins/` ou qualquer diretório arbitrário fornecido pelo Customer.

Minecraft `.jar`, ZIPs e outros artifacts permitidos entram por staging/confinement, checksum, validação e então originam um `ContentAssignment` canônico. O File Manager não é uma rota alternativa de instalação de conteúdo gerenciado.

### U6-M — Minecraft Providers / Modpacks — concluída

Minecraft recebe providers de primeira classe no mesmo UCP:

1. Modrinth como provider canônico;
2. CurseForge para mods e modpacks;
3. ATLauncher pode ser avaliado para modpacks depois dos dois providers principais.

O provider é somente a origem. Ativação pertence à U5/U5-M, segurança à U7 e update/rollback à U9.

A resolução deve considerar versão do Minecraft, loader/runtime e compatibilidade declarada antes de produzir o artifact canônico.

Tracker: #490.

## Modpacks como conteúdo composto

Um modpack não é tratado como um arquivo solto nem como uma lista plana de JARs. O UCP deve introduzir um contrato composto de revisão/bundle capaz de registrar:

- identidade e versão do pack;
- versão Minecraft;
- runtime/loader e versão exigida;
- manifesto resolvido;
- mods/plugins/dependências;
- conteúdo adicionado/removido/atualizado;
- configuração gerenciada (`config/`, `defaultconfigs/`, `kubejs/` ou equivalentes quando declarados);
- proveniência do provider e checksums;
- revisão ativa e revisão anterior.

Esse contrato é a base para atualização transacional e rollback da U9.

## U7 — Security / Malware Scan — concluída

U7 é obrigatória para conteúdo Minecraft, Steam/Workshop e uploads externos. O fluxo converge para estados comuns: `unscanned`, `clean`, `suspicious`, `blocked` e `scan_failed`; provider ou jogo não podem alterar essa semântica.

O pipeline canônico no Agent é:

```text
provider/upload
  → staging/quarantine
  → validação de tamanho/checksum nativo
  → YARA-X no artefato recebido
  → extração segura, quando aplicável
  → YARA-X no payload expandido
  → managed content
  → U5 activation snapshot
  → runtime
```

A partir de `security_policy_version=1`, **somente `clean` pode entrar no activation snapshot**. `suspicious` e `blocked` são verdicts terminais para a mesma revisão/checksum e exigem nova revisão ou intervenção administrativa; `scan_failed` é fail-closed e retryable, para permitir recuperação quando engine/regras voltarem a estar disponíveis. O scanner nunca recebe lógica específica de Minecraft, Steam ou provider.

O Agent anuncia `content_security_contract=1` e o estado factual de `content_security`. Novos artefatos/revisões falham de forma fechada se `yr` ou as regras estiverem ausentes. As regras são operator-managed: Linux usa por padrão `/etc/capivara-agent-security/yara-rules` (root-owned) e Windows `%PROGRAMDATA%\CapivaraAgent\security\yara-rules` (ACL de SYSTEM/Administrators). O projeto não baixa automaticamente regras de terceiros.

Para rollout seguro, estados `applied` criados antes da U7 e sem `security_policy_version` são temporariamente grandfathered; não são desativados cegamente no upgrade. Ao serem reconciliados/revisados, passam pela policy v1 e só voltam/continuam ativáveis após verdict `clean`. Isso evita indisponibilidade em massa sem criar bypass para conteúdo novo.

## U8 — Dashboard — em andamento

O Dashboard deve apresentar uma superfície universal orientada por capacidades:

- mods;
- plugins;
- modpacks;
- Steam Workshop;
- datapacks quando suportados;
- provider/origem;
- versão/compatibilidade;
- segurança;
- instalação/remoção;
- enable/disable;
- reorder quando semanticamente aplicável;
- update/rollback quando disponíveis.

O Dashboard expressa desired state; ele não materializa regras específicas de Paper, NeoForge, DayZ ou outros runtimes.

U8 usa `/api/customer/instance/workspace/content` como superfície Customer canônica. A descoberta de provider é filtrada pelo `RuntimeDefinition`: tipos gerenciados declaram providers pesquisáveis e bundles declaram providers de modpack. A UI mostra o último `agent_content_state` alinhado à revisão desejada, incluindo verdict efetivo de segurança, estado de reconciliação e versão instalada. Children internos de modpack permanecem ocultos como ações independentes; o pai agrega o estado do bundle. External Upload entra pela mesma lista após Artifact Transfer/quarantine e nunca escreve diretamente em diretórios nativos de mods/plugins.

Tracker: #505.

## U9 — Updates / Rollback — em andamento

U9 usa as revisões imutáveis já persistidas por UCP, sem tabela paralela de updates. Update de conteúdo estruturado é server-resolved: o Customer solicita `update`, mas URL, hash e versão continuam pertencendo ao Controller/provider resolver. Modrinth/CurseForge usam a identidade de projeto persistida na provenance; Workshop usa `PublishedFileId` canônico.

Rollback nunca decrementa o contador de revisão. Uma revisão histórica é materializada novamente como **nova desired revision**, marcada com provenance de rollback e submetida outra vez ao gate U7. Quando o Agent restaura fisicamente a revisão anterior após falha de readiness, ele reporta `status=rolled_back` com a `applied_revision` anterior; o heartbeat converge o desired state do Controller para essa revisão histórica.

Modpacks preservam a mesma semântica como unidade composta: cada bundle revision mantém manifesto, provider/version, loader e overrides; update calcula `added/removed/updated/unchanged`, e rollback recompõe pai + children a partir da revisão histórica, criando uma nova bundle revision. Falha de readiness de um child pode reverter o bundle pai inteiro.

Transições de Minecraft version/loader continuam fail-closed no resolver atual; não são tratadas como simples troca de JAR. Como U9 só aceita update dentro do runtime/loader corrente, backup obrigatório de save/config fica reservado para a futura transição de runtime de maior risco, onde deverá existir checkpoint concluído antes da promoção.

A camada Agent continua responsável por staging, checksum, U7 scan, ativação, restart/readiness e rollback da projeção/target; Controller/Dashboard apenas coordenam revisions e desired state. Linux/Windows compartilham o mesmo contrato `rolled_back`.

Tracker: #509.

## U10 — E2E Linux/Windows

O UCP não é considerado universalmente provado sem uma matriz representativa que inclua:

- DayZ/Project Zomboid já cobertos pela U5;
- Paper + plugin;
- NeoForge ou Fabric + mod;
- modpack vindo de provider;
- external upload;
- enable/disable e reorder quando aplicável;
- restart/readiness;
- update + rollback;
- isolamento entre instâncias;
- paridade Linux/Windows.

Tracker dos gates Minecraft: #491.

## U11 — Cleanup / Migration

U11 deve provar que não restou um sistema paralelo de mods/plugins Minecraft fora do UCP. Fluxos legados podem existir durante a migração, mas o estado final precisa ter uma única autoridade para instalação, ativação, segurança, update e rollback.

Isso inclui retirar qualquer caminho em que File Manager, Dashboard ou scripts legados instalem conteúdo gerenciado diretamente em `mods/`/`plugins/` sem passar pelo contrato canônico.

## Segurança

- comandos, scripts e shell em artifacts são rejeitados pelo contrato;
- targets absolutos, `..` e escapes do diretório da instância são rejeitados;
- downloads remotos exigem HTTPS e allowlist/política do provider;
- checksum é validado quando declarado e deve ser preservado na proveniência;
- ZIP/TAR são inspecionados contra traversal; links e special files perigosos são recusados;
- artifacts `local` só podem vir de raízes confinadas definidas pelo Agent;
- o Agent valida ownership da instância antes de instalar ou remover;
- instalação usa staging e troca atômica; remoção só alcança o target gerenciado;
- provider não autoriza automaticamente ativação;
- conteúdo incompatível com RuntimeDefinition falha fechado.

Providers especializados devem resolver para um artifact/manifesto confiável antes do reconciler. Isso evita transformar C4 em execução remota arbitrária.

## Persistência

A persistência canônica mantém:

- `content_assignments`: desired state atual;
- `content_assignment_revisions`: histórico imutável;
- `agent_content_state`: projeção aplicada/reportada pelo Agent.

A identidade de uma atribuição é `(instance_id, content_id)` e alterações incrementam `revision`. Conteúdo idêntico é no-op idempotente. U9 pode evoluir o histórico para representar explicitamente revisões compostas de modpack sem criar um segundo content store.

## Eventos e observabilidade

Alterações administrativas publicam eventos semânticos na Universal Event Platform. O UCP não produz um Universal Event por heartbeat ou por byte transferido. Métricas detalhadas de transferência/provider pertencem à plataforma de observabilidade sem acoplar o content store ao sistema de métricas.

## Interfaces

Controller CLI:

```text
cap content-store list
cap content-store set ...
cap content-store history <assignment-id>
```

HTTP administrativo permanece sobre a superfície canônica de conteúdo; novas rotas Customer/provider devem convergir ao mesmo serviço e ao mesmo modelo de autorização.

## Compatibilidade e migração

`installer/content_manager.sh`, `content_planner.sh`, providers existentes e `content_installations` podem continuar disponíveis somente enquanto houver consumidores legados explícitos. U11 deve migrar ou retirar esses caminhos de modo que Minecraft e jogos Steam não mantenham planos paralelos de conteúdo.

## Rebaseline oficial

O roadmap canônico a partir de #488 é:

```text
U1-U4  concluídas
U5     concluída (core universal)
U5-M   Minecraft activation adapters
U6     External Upload
U6-M   Minecraft providers + modpacks
U7     Security / Malware Scan
U8     Dashboard universal incluindo Minecraft
U9     Updates / Rollback incluindo modpacks
U10    E2E Linux/Windows + matriz Minecraft
U11    Cleanup / Migration sem sistemas paralelos
```

O critério final é simples: o Universal Content Platform só está completo quando Minecraft não depende de um subsistema separado de mods/plugins/modpacks.
