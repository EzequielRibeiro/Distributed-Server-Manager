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

## Primeira versão

Somente runtime Minecraft Java **NeoForge**, com arquivo ZIP já transferido pelo
próprio usuário e confirmado pelo Agent. Não é um conversor geral de qualquer
exportação CurseForge: ZIP com `manifest.json` e referências a downloads continua
bloqueado. Server packs com scripts que baixam mods em tempo de instalação, sem
`mods/*.jar` incluídos, também não são aceitos.

Fluxo:
1. Cliente realiza backup e para a instância. Baixa o ZIP no site/app oficial do autor.
2. Em **Conteúdo > Enviar arquivo**, escolhe `Modpack`, ZIP, ID do projeto e ID do
   arquivo publicados pelo CurseForge, além da versão exata do NeoForge.
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

### Validação offline inicial, antes de ativar o fluxo

Copiar manualmente o ZIP baixado do site oficial para o host de teste e executar:

```bash
python3 scripts/minecraft_serverpack_preflight.py \
  /caminho/ServerFiles-0.9.0-beta.zip \
  --minecraft 26.1.2 --loader neoforge --loader-build 26.1.2.109
```

Esta verificação é apenas estrutural e local; **não comprova origem** por si
só. A prévia autenticada, depois do upload pelo cliente, exige correspondência
de SHA-1 no CurseForge, versão da instância e loader. Não disponibilizar
instalação até passar pelos dois diagnósticos e concluir um ciclo de
homologação de segurança + backup/rollback com o ZIP real.

### Condições de parada

- Projeto/file ID incorretos, SHA oficial ausente ou divergente;
- versão Minecraft ou loader não comprovada, diverge do arquivo publicado
  ou do NeoForge instalado;
- links simbólicos, paths inseguros, compressão inválida, excesso de entradas,
  executáveis dentro de pastas aprovadas de configurações, mods fora de mods/;
- instância ainda em execução, scanner reprovado ou mod inválido;
- falta de capacidade de Agent e/ou permissão de upload/mods/modpack.

**Não usar** o recurso para ignorar licença, substituir o runtime ou aplicar
mudanças sobre um mundo ativo. O pacote oficial real ainda precisa de QA
antes da implantação e da release.
