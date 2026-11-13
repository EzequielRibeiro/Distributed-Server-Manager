# Homologacao de boot de mundo restaurado — Minecraft 005 (#1013)

A migracao ATM11 0.13→0.14 e boot da distribuicao oficial 0.14.0-beta,
NeoForge 26.1.2.126, com 291 mods, foram comprovados isoladamente no CI.
Em 12/11, o ultimo backup fisico do Minecraft 005 foi validado por SHA-256
e restaurado com o Agent em sandbox (5.358 arquivos, 2.986.410.210 bytes).
**Ainda falta iniciar o jogo com esse mundo restaurado** para homologar
a recuperacao de ponta a ponta.

## Etapa zero: preflight read-only

O verificador analisa o manifesto inicial do TAR.GZ, identidade de instancia,
disponibilidade de memoria e disco, carga do host, socket TCP local e systemd.
**Nao extrai, inicia, para ou modifica nenhum servidor.** Exige no minimo
12 GiB de memoria efetivamente disponivel e 12 GiB livres de armazenamento
(ou mais, conforme tamanho do backup). Essas margens sao precondicoes,
nao garantia de que o jogo funcionara.

```sh
python3 scripts/minecraft_restored_world_boot_preflight.py \
  --archive /opt/dsm/runtime/hybrid-agent-state/backups/cli-000001-minecraft-005/87fea2fa-1ff5-44b5-8f74-8c819ff86072.tar.gz \
  --sandbox-parent /tmp \
  --instance-id cli-000001-minecraft-005 \
  --backup-id 87fea2fa-1ff5-44b5-8f74-8c819ff86072 \
  --port 25596
```

So prosseguir se `status=preflight_pass` e exit 0; exit 2 significa
**nao iniciar o boot neste host**. A leitura do primeiro manifesto
**nao verifica novamente o SHA-256 do backup**, que deve ser comprovado
separadamente por hash fisico contra os metadados do Controller.

## Homologacao subsequente em host descartavel, preferencialmente Node1

- Node1 esta offline; **nao utilizar Horizon como alternativa automatica**
  quando o preflight bloquear memoria, CPU, portas ou disco.
- Transferir o backup privado apenas por canal autenticado para destino
  descartavel autorizado, verificando SHA-256; nao anexar mundos ou dados
  de jogadores como artefatos de CI publicos.
- Usar o Agent de restauracao sob *root de instancia ficticia*, com
  diretório temporario e estado parado, nunca apontando para um service
  ou um volume de producao. Nao manipular os backups originais.
- Preparar o NeoForge da revisao instalada, com exatamente 291 mods,
  e ajustar somente na **copia descartavel** a escuta para loopback
  `127.0.0.1:25596`, desabilitando RCON/query/portas externas.
- Executar o Java em unit systemd descartavel sem restart automatico,
  usuario nao-root, resource limits (ex.: `MemoryMax=8G`), isolamento
  de rede para loopback, working dir da copia, `KillMode=control-group`.
- Exigir `Done` na janela do log do boot corrente, status ping TCP
  Minecraft 1.21+ respondendo na porta isolada, mods/loader confirmados,
  level.dat do mundo restaurado e desligamento sem corrupcao.
- Comprovar nenhuma alteracao ao mundo e servidor originais, encerrar unit
  e eliminar apenas o workspace descartavel; produzir relatorio com
  sucesso/falha e checksums, sem dados privados.

O preflight de recursos **nao cria a unit, nao executa o jogo e nao
substitui a homologacao posterior**. O gate de release deve continuar
bloqueado ate essa validacao real e ate o armazenamento de 14 dias
passar com margem operacional.
