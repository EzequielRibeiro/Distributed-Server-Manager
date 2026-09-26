# Importação manual de Server Packs oficiais — Minecraft (v1)

Status: implementado na branch **feat/minecraft-official-serverpack-import**, em
homologação. Não está instalado em /opt/dsm e não foi liberado para clientes.

## Motivação

ATM11 possui pelo menos um mod cujo autor desabilitou downloads por ferramentas
de terceiros. Respeitar esse bloqueio é obrigatório: não reconstruir downloads,
não utilizar espelhos presumidos e não omitir um mod obrigatório. Como alternativa,
o usuário pode baixar o ZIP **ServerFiles-0.9.0-beta.zip** diretamente do autor na
página original do CurseForge (projeto **1148445**, arquivo **8916964**).
O Capivara nunca baixa esse ZIP em nome do usuário via API restrita.

## Descoberta automática e atualização incremental

A seleção de modpacks agora prioriza o Server Pack oficial disponível
pela API CurseForge (`serverPackFileId`/`isServerPack`), com download
apenas quando o provedor autoriza e o SHA-1 do ZIP original é verificado
antes de enfileirar a transferência para o Agent. No Modrinth,
o fluxo usa o resolvedor existente de arquivos `.mrpack` compatíveis
com o servidor. Downloads restritos devem usar upload manual do
arquivo fornecido diretamente pelo autor.

**Uma nova versão do modpack não reinstala o servidor Minecraft.**
O mesmo `instance_id` e `content_id` são preservados: a prévia identifica
a revisão instalada e mostra o delta de mods adicionados, alterados,
removidos e inalterados. A nova versão exige correspondência exata da
revisão conferida na prévia e confirmação explícita de backup e instância
parada. Outra versão publicada não pode criar um segundo modpack ativo
na mesma instância sem atualização do ID existente.

- Uma atualização normal não pode alterar o projeto de origem, a versão
  Minecraft, o loader ou seu build. Mudanças dessas identidades exigem
  uma migração separada, com backup.
- Mundo, dados dos jogadores, configurações de rede, identidade da
  instância e backups estão fora do armazenamento gerenciado dos mods
  e **não são substituídos por uma atualização**.
- Ao aplicar uma atualização, o materializador Linux/Windows preserva
  as configurações existentes, inclusive personalizações locais;
  os defaults novos do ZIP não sobrescrevem os arquivos atuais.
  Configurações novas exigidas pelo pacote precisam de revisão/migração
  explícita em procedimento separado.
- Mods do Server Pack conservam IDs derivados do caminho e versões por
  SHA256. O Agent reutiliza os idênticos, enquanto a projeção nativa
  evita copiar novamente arquivos byte a byte iguais.
- O banco mantém o histórico e o diff do bundle e oferece reversão
  de revisões gerenciadas.

**Pendente para liberação:** um teste real de atualização com ZIP
original, backup verificável, recuperação de falha parcial quando
há mods removidos e retenção de artefatos antigos para rollback.
A confirmação do usuário de que existe backup não comprova
automaticamente sua integridade. Não efetuar merge/release até
homologar essas condições em um Agent isolado.

## Descoberta e instalação por provedor

O Controller consulta as versões compatíveis antes de solicitar a instalação:

- **CurseForge:** identifica o ZIP oficial pelos campos `isServerPack` e
  `serverPackFileId`. Quando o autor e o endpoint permitem distribuição, usa
  somente o CDN oficial, verifica o SHA-1 publicado **antes de enfileirar** a
  transferência, depois exige a mesma conferência no preview autenticado.
  Respostas 403 ou arquivos sem metadados suficientes resultam em **envio
  manual pelo cliente**; nunca se supõe uma URL nem se ignora um mod obrigatório.
- **Modrinth:** localiza a versão `.mrpack` compatível no catálogo e aproveita
  o resolvedor existente, respeitando componentes exclusivos do cliente,
  hashes, loaders e regras de servidor. O Modrinth não garante a publicação
  de um ZIP de servidor separado.

Na UI, antes de cada operação, o cliente vê o pacote identificado, tamanho,
versão e confirma a preparação. Uma operação de instalação completa só pode
ser registrada depois de backup confirmado, instância parada, preview de
integridade e validações de segurança do Agent. A revisão incremental compara
mods adicionados, atualizados, removidos e inalterados e mantém os arquivos do
mundo e configurações não gerenciadas; rollback usa as revisões existentes.

## Primeira versão

Somente runtime Minecraft Java **NeoForge**. Quando o download automático
não é autorizado, aceita um ZIP original já obtido pelo próprio usuário e
confirmado pelo Agent. Não é um conversor geral de qualquer
exportação CurseForge: ZIP com `manifest.json` e referências a downloads continua
bloqueado. Server packs com scripts que baixam mods em tempo de instalação, sem
`mods/*.jar` incluídos, também não são aceitos.

Fluxo:
1. Cliente realiza backup e para a instância. O Controller consulta o arquivo oficial
   e o transfere pelo CDN autorizado. Caso haja restrição, o cliente pode obter
   o ZIP diretamente no site/app do autor.
2. Para envio manual, em **Conteúdo > Enviar arquivo**, escolhe `Modpack`, ZIP
   e os IDs oficiais do projeto e arquivo do CurseForge. A versão exata do
   NeoForge é inferida do instalador presente no ZIP, sem executá-lo; somente
   pacotes sem essa evidência exigem indicação manual, posteriormente validada.
3. Controller envia o ZIP pelo mecanismo de transferência existente. O Agent
   coloca em quarentena, inspeciona a estrutura e confirma SHA256.
4. **Prévia obrigatória**: Controller lê apenas o ZIP original, valida caminhos,
   limites, versão declarada, estrutura, calcula SHA256 de cada mod e comprova
   origem comparando **nome, tamanho e SHA-1** com metadados oficiais do
   projeto/arquivo informados. Exige confirmação explícita na interface.
5. Somente após confirmação, Controller registra um bundle atômico no banco com
   dependências dos mods para o ZIP pai. A pasta de mods passa pelo scanner e
   pela validação semântica do Agent antes da projeção.
6. O Agent recusa instalar enquanto a instância estiver em execução; verifica
   o NeoForge efetivamente instalado por arquivos de biblioteca/launcher locais.
   Todos os mods são adquiridos exclusivamente do ZIP original já verificado,
   conferidos por SHA256 e submetidos ao scanner e marcadores de mod.
7. As configurações de pastas previamente autorizadas são projetadas pelo
   mecanismo existente de overrides, que impede sobrescrever arquivos não
   gerenciados e possui reversão. Os scripts de inicialização do ZIP nunca
   são executados nem projetados sobre os arquivos de runtime.
8. O bundle e seus arquivos possuem histórico/revisões e aproveitam o
   reconciliador, a recuperação e o rollback de conteúdo existentes.

Limites v1: 4 GiB ZIP, 8 GiB expandido, 12 mil entradas, 1500 mods e no máximo
8 pastas aprovadas de configuração. O processamento do Agent permite 2000
comandos, mantendo o limite de 2000 assignments do Controller.


## Preservação obrigatória de mundos ao enviar novas versões

Uma nova versão do modpack é uma **revisão de conteúdo**, nunca uma
reinstalação da instância ou uma autorização implícita para fazer *wipe*.
A atualização deve conservar o mesmo `instance_id`, `content_id`,
`server.properties` e o `level-name`. O Controller confronta as revisões,
recusa mudanças incompatíveis de Minecraft/NeoForge e exige confirmação de
backup para atualizações do Server Pack oficial. A remoção, adição ou troca de
um mod não remove nem reconstrói o mundo.

Em **ambos** os Agents, o materializador impede que overrides de qualquer
modpack sejam projetados sobre os mundos padrão, o mundo configurado em
`level-name`, Nether/End, `worlds/`, `dimensions/`,
arquivos de região `.mca`/`.mcr`, `level.dat`, dados de jogadores,
ou `server.properties`. Os novos scripts do pacote permanecem inertes.
A atualização oficial também preserva as configurações existentes e não
recopia mods que não mudaram. Em caso de incompatibilidade, interromper
a operação e oferecer rollback do **conteúdo**, nunca recriação do mapa.

### Evidência obrigatória na homologação real

Com o **servidor Minecraft parado** e um backup concluído e verificado,
registre o estado do mundo antes de aplicar a nova versão:

```bash
python3 scripts/minecraft_modpack_world_audit.py \
  --instance-root "/caminho/da/instancia/game-data" \
  --save-baseline "/home/ezequiel/dsm-test-evidence/minecraft-world-before.json"
```

Após reconciliação dos novos mods, **antes de iniciar o Minecraft**,
confirme que nenhum arquivo do mundo mudou:

```bash
python3 scripts/minecraft_modpack_world_audit.py \
  --instance-root "/caminho/da/instancia/game-data" \
  --compare-baseline "/home/ezequiel/dsm-test-evidence/minecraft-world-before.json"
```

A segunda verificação deve retornar `WORLD_UNCHANGED`. Retornos
`WORLD_PRESERVATION_FAILED` ou `WORLD_AUDIT_ERROR` bloqueiam a
homologação, reinício e release até diagnóstico e eventual restauração do
backup. O script é somente leitura para a instância: verifica SHA-256 de
regiões, dimensões, dados de jogadores e demais arquivos presentes nos
diretórios de mundo. Salva o relatório fora da instância.

Após o primeiro reinício, mods podem modificar **novos chunks ou formatos
de mundo** conforme suas próprias regras. Os guards do Capivara impedem
reinstalação/overwrite pelo gerenciador; não constituem garantia de
compatibilidade de *worldgen* entre versões de mods. Guardar backup e
validar o primeiro boot antes de declarar a atualização concluída.

### Validação offline inicial, antes de ativar o fluxo

Com um ZIP oficial obtido por download autorizado ou enviado pelo cliente,
inspecionar sua estrutura sem instalar componentes:

```bash
python3 scripts/minecraft_serverpack_preflight.py \
  /caminho/ServerFiles-0.9.0-beta.zip \
  --minecraft 26.1.2 --loader neoforge
```

Esta verificação é apenas estrutural e local; **não comprova origem** por si
só. A prévia autenticada, depois do upload pelo cliente, exige correspondência
de SHA-1 no CurseForge, versão da instância e loader. Não disponibilizar
instalação até passar pelos dois diagnósticos e concluir um ciclo de
homologação de segurança + backup/rollback com o ZIP real.

### Evidências reais ATM11 0.9.0-beta (26/09/2026)

Download pela API foi **autorizado** para o projeto 1148445, arquivo
Server Pack 8916964. O ZIP real foi baixado uma vez, verificado pelo
SHA-1 oficial, e recebeu SHA-256
`3d1ed149bcdeb793777e1c846ffe439600eae7913837fd027077946f4e59fcc3`.
Possui 518.936.896 bytes, 1.925 entradas e aproximadamente 0,56 GiB
descompactado: **254 JARs de mods de servidor** e diretórios aprovados
`config/` e `kubejs/`. O próprio ZIP inclui
`neoforge-26.1.2.109-installer.jar`, `startserver.sh` e
`startserver.bat`, que concordam com a versão exata **26.1.2.109**.
O importador pode inferir e validar essa versão por leitura; **jamais
executa o instalador ou os scripts de inicialização**. A entrada
`local/kubejs/dev.json` não é projetada no runtime gerenciado.

O host de testes disponibilizou **36 arquivos de mundo** para uma
baseline SHA-256 e recebeu `WORLD_UNCHANGED`; ainda não houve
ativação do pacote real nem comparação pós-atualização. O filesystem
raiz estava com cerca de 7,5 GiB livres e 92% de utilização; verificar
capacidade de backup e reserva antes da instalação. A versão ativa
do NeoForge na instância 003 ainda necessita comprovação por leitura
dos metadados protegidos do runtime.

### Condições de parada

- Projeto/file ID incorretos, SHA oficial ausente ou divergente;
- versão Minecraft ou loader não comprovada, diverge do arquivo publicado
  ou do NeoForge instalado;
- links simbólicos, paths inseguros, compressão inválida, excesso de entradas,
  executáveis dentro de pastas aprovadas de configurações, mods fora de mods/;
- instância ainda em execução, scanner reprovado ou mod inválido;
- falta de capacidade de Agent e/ou permissão de upload/mods/modpack.

**Não usar** o recurso para ignorar licença, substituir o runtime ou aplicar
mudanças sobre um mundo ativo.

**Integração obrigatória para a release:** PR #837 contém as correções de
pesquisa unificada e do resolvedor CurseForge. Há sobreposição na UI com este
PR #839. Antes de qualquer merge, conciliar os dois conjuntos de alterações,
executar novamente testes de regressão e homologar o ZIP original e o Agent
real no host. Aprovação em CI não substitui esse teste. O pacote oficial real ainda precisa de QA
antes da implantação e da release.
