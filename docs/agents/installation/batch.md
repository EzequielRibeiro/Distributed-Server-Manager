# Instalação de Agents em lote

Este guia mostra como instalar vários Capivara Agents a partir de um único arquivo CSV, incluindo hosts **Linux e Windows no mesmo lote**.

O fluxo recomendado usa **OpenSSH para as duas plataformas**. Para Linux, o lote também pode usar um **pacote local armazenado no Controller**, transferido por SCP para cada host antes da instalação.

> A senha do usuário remoto nunca deve ser escrita diretamente no CSV. O CSV contém somente o caminho para um arquivo secreto protegido existente no Controller.

## Métodos disponíveis no lote

| Plataforma | Método | Fonte do Agent |
|---|---|---|
| Linux | `ssh` | GitHub Release recomendada ou `release_tag` específica |
| Linux | `ssh` + `package_file` | Pacote local `.tar.gz` existente no Controller |
| Windows | `ssh` | GitHub Release recomendada ou `release_tag` específica |
| Windows | `winrm` | GitHub Release recomendada ou `release_tag` específica |

Pacote local em lote está disponível **somente para Linux**. O Windows ainda não possui no core um fluxo equivalente de validação e transferência de ZIP local.

## Pré-requisitos

No Controller ou instalação Hybrid:

- `cap agent deploy-batch` disponível;
- conectividade TCP do Controller até a porta SSH dos hosts;
- OpenSSH Server ativo nos hosts Linux e Windows quando `method=ssh`;
- usuário remoto com privilégios administrativos suficientes para instalar o Agent;
- região, datacenter e Controller já cadastrados;
- `sshpass` instalado no Controller quando for usada autenticação por `password_file`;
- para pacote local Linux, o arquivo deve estar no diretório autorizado de pacotes do Controller.

Para Windows em lote via OpenSSH, o usuário pode ser `Administrator` ou outra conta administrativa permitida pelo host.

## 1. Criar os arquivos secretos de senha

Crie um secret separado para cada senha/host quando as credenciais forem diferentes:

```bash
sudo cap agent secret create node-linux-01
sudo cap agent secret create node-linux-02
sudo cap agent secret create node-windows-01
```

Por padrão, os arquivos ficam em:

```text
/etc/capivara/secrets/remote-deploy/
```

Os arquivos de segredo devem permanecer com permissão `0600`. Nunca use `cat` para exibir a senha durante diagnóstico ou documentação.

## 2. Testar os hosts antes do lote

O teste é não destrutivo e não instala o Agent.

Linux:

```bash
sudo cap agent test-connection 192.168.15.60 \
  --platform linux \
  --ssh-user capadmin \
  --password-file /etc/capivara/secrets/remote-deploy/node-linux-01.secret
```

Windows com OpenSSH:

```bash
sudo cap agent test-connection 192.168.15.70 \
  --platform windows \
  --ssh-user Administrator \
  --password-file /etc/capivara/secrets/remote-deploy/node-windows-01.secret
```

Faça esse teste pelo menos em um host representativo de cada plataforma antes de iniciar um lote grande.

## 3. Instalação usando GitHub Release

Exemplo de CSV misto Linux/Windows usando a release estável recomendada:

```csv
host,ssh_user,platform,method,ssh_port,password_file,package_file,controller_id,controller_url,region_id,datacenter_id,name,port_range,port_protocol,release_tag,bootstrap_timeout
192.168.15.60,capadmin,linux,ssh,22,/etc/capivara/secrets/remote-deploy/node-linux-01.secret,,controller-horizon,https://controller.capivaradsm.com.br:9443,br,sp01,Node Linux 01,24000-24999,both,,900
192.168.15.70,Administrator,windows,ssh,22,/etc/capivara/secrets/remote-deploy/node-windows-01.secret,,controller-horizon,https://controller.capivaradsm.com.br:9443,br,sp01,Node Windows 01,26000-26999,both,,900
```

Quando `release_tag` fica vazio e `package_file` também está vazio, a Dashboard seleciona a release estável recomendada para a plataforma.

Para fixar uma versão, informe por exemplo:

```text
release_tag=v2.0.20
```

## 4. Instalação Linux usando pacote local do Controller

O pacote local deve ser um pacote oficial Linux do Capivara, por exemplo:

```text
capivara-agent-linux-2.0.20.tar.gz
```

### 4.1 Gerar o pacote local

No clone atualizado do repositório do Controller:

```bash
cd /home/ezequiel/Distributed-Server-Manager-clean

rm -rf /tmp/capivara-linux-package
mkdir -p /tmp/capivara-linux-package

bash release/build_agent_package.sh \
  HEAD \
  /tmp/capivara-linux-package
```

O builder gera:

```text
capivara-agent-linux-VERSAO.tar.gz
capivara-agent-linux-VERSAO.tar.gz.sha256
capivara-agent-linux-VERSAO.manifest.json
```

A versão é obtida do commit `HEAD`. Portanto, gere o pacote somente depois que a versão desejada estiver commitada.

Exemplo de saída para 2.0.20:

```text
/tmp/capivara-linux-package/capivara-agent-linux-2.0.20.tar.gz
```

### 4.2 Preparar a área protegida do Controller

O diretório padrão autorizado no Controller é:

```text
/var/lib/capivara/agent-packages
```

Crie o diretório se necessário:

```bash
sudo install -d \
  -o capivara \
  -g capivara \
  -m 0750 \
  /var/lib/capivara/agent-packages
```

Copie o pacote gerado:

```bash
sudo install \
  -o capivara \
  -g capivara \
  -m 0640 \
  /tmp/capivara-linux-package/capivara-agent-linux-2.0.20.tar.gz \
  /var/lib/capivara/agent-packages/capivara-agent-linux-2.0.20.tar.gz
```

Confirme que o serviço consegue ler o pacote:

```bash
sudo -u capivara test -r \
  /var/lib/capivara/agent-packages/capivara-agent-linux-2.0.20.tar.gz \
  && echo "[OK] Capivara consegue ler o pacote" \
  || echo "[ERRO] Capivara não consegue ler o pacote"
```

O diretório pode ser alterado com a variável:

```text
DSM_AGENT_LOCAL_PACKAGE_DIR
```

### 4.3 Validar o pacote antes do lote

Use o mesmo validador empregado pelo backend:

```bash
cd /home/ezequiel/Distributed-Server-Manager-clean

PYTHONPATH=. python3 - <<'PY'
from core.agent_ssh_deploy import validate_agent_package_file

path = "/var/lib/capivara/agent-packages/capivara-agent-linux-2.0.20.tar.gz"
validated = validate_agent_package_file(path)
print("[OK] Pacote Capivara validado:")
print(validated)
PY
```

### 4.4 CSV com pacote local

```csv
host,ssh_user,platform,method,ssh_port,password_file,package_file,controller_id,controller_url,region_id,datacenter_id,name,port_range,port_protocol,release_tag,bootstrap_timeout
192.168.15.61,capadmin,linux,ssh,22,/etc/capivara/secrets/remote-deploy/node-linux-02.secret,/var/lib/capivara/agent-packages/capivara-agent-linux-2.0.20.tar.gz,controller-horizon,https://controller.capivaradsm.com.br:9443,br,sp01,Node Linux 02,25000-25999,both,,900
```

Para várias máquinas Linux, várias linhas podem reutilizar o mesmo `package_file`.

### O que o Controller faz

Quando `package_file` é informado, o Controller:

1. confirma que o caminho está dentro do diretório autorizado;
2. confirma que o arquivo existe;
3. executa o preflight SSH do host;
4. recusa instalação automática se já detectar um Capivara Agent no destino;
5. valida o pacote Linux antes da transferência;
6. verifica estrutura, `manifest.json`, `VERSION`, arquivos obrigatórios, tamanho e SHA-256;
7. transfere o pacote por SCP para um caminho temporário seguro;
8. executa o instalador do pacote no host;
9. remove o arquivo temporário;
10. prossegue com pairing, identidade permanente e heartbeat.

O pacote local **não é enviado pelo navegador**. O CSV contém somente o caminho administrativo do arquivo já existente no Controller.

## 5. Campos do CSV

| Campo | Uso |
|---|---|
| `host` | IP ou hostname alcançável pelo Controller. Obrigatório. |
| `ssh_user` | Usuário usado pelo OpenSSH. Obrigatório no lote da Dashboard. |
| `platform` | `linux` ou `windows`. |
| `method` | `ssh` ou `winrm`. `package_file` exige `ssh`. |
| `ssh_port` | Porta do OpenSSH. Padrão `22`. |
| `password_file` | Caminho do secret protegido no Controller. Nunca coloque a senha aqui. |
| `package_file` | Pacote local Linux no Controller. Opcional. |
| `controller_id` | ID lógico do Controller que receberá o Agent. |
| `controller_url` | URL que o Agent usará para alcançar o Controller após o bootstrap. |
| `region_id` | Região administrativa. Obrigatório na Dashboard. |
| `datacenter_id` | Datacenter administrativo. Obrigatório na Dashboard. |
| `name` | Nome amigável do Agent. |
| `port_range` | Faixa reservada para instâncias, por exemplo `24000-24999`. |
| `port_protocol` | `tcp`, `udp` ou `both`. |
| `release_tag` | Release específica. Não use junto com `package_file`. |
| `bootstrap_timeout` | Timeout do bootstrap em segundos. Exemplo: `900`. |

A ordem das colunas pode ser alterada. O parser associa os valores pelo nome do cabeçalho, não por posição fixa. Preserve os nomes dos campos exatamente como documentados.

## 6. Regras e validações

- `host`, `ssh_user`, `region_id` e `datacenter_id` são obrigatórios na Dashboard;
- `platform` aceita somente `linux` ou `windows`;
- `method` aceita `ssh` ou `winrm` no lote remoto;
- `package_file` só pode ser usado com `method=ssh`;
- `package_file` só está disponível para `platform=linux`;
- `package_file` e `release_tag` não podem ser usados juntos na mesma linha;
- `password`, `ssh_password` e `winrm_password` em texto puro são recusados;
- `identity_file` não é aceito pela Dashboard; configure a identidade SSH no Controller;
- `password_file` precisa existir no Controller e ficar no diretório autorizado de secrets;
- `package_file` precisa existir no Controller e ficar no diretório autorizado de pacotes;
- hosts duplicados no mesmo CSV são recusados;
- uma linha deve representar um único Agent;
- evite faixas de portas conflitantes com a política de placement.

## 7. Proteção contra reexecução do lote

A Dashboard calcula uma identificação do conteúdo do CSV e mantém histórico local das execuções recentes.

Enquanto o lote estiver rodando, o botão permanece bloqueado. Depois da conclusão, o botão passa a indicar **Executar novamente**.

Se o mesmo CSV for enviado outra vez no mesmo navegador, a Dashboard exige confirmação explícita antes da nova execução.

Além disso, o Controller executa preflight remoto e recusa reinstalação automática quando já detecta um Capivara Agent no host.

Essa proteção evita o caso comum de duplo clique, refresh ou reenvio acidental. Uma reexecução intencional continua possível mediante confirmação administrativa.

## 8. Instalar pela Dashboard

Na Dashboard administrativa:

1. abra **Agents**;
2. escolha **Adicionar Agent**;
3. escolha **Agents em lote**;
4. selecione o arquivo `.csv`;
5. opcionalmente marque **Continuar em caso de erro**;
6. inicie **Instalar Agents em lote**;
7. acompanhe o resultado de cada linha.

No resultado, a Dashboard identifica se a solicitação usou `release` ou `pacote local`.

## 9. Instalar pela CLI

O mesmo CSV pode ser executado diretamente no Controller:

```bash
sudo cap agent deploy-batch ~/capivara-agents.csv
```

Para continuar após falhas:

```bash
sudo cap agent deploy-batch \
  ~/capivara-agents.csv \
  --continue-on-error
```

Para saída estruturada:

```bash
sudo cap agent deploy-batch \
  ~/capivara-agents.csv \
  --continue-on-error \
  --json
```

Consulte os campos adicionais aceitos pelo CLI com:

```bash
cap agent deploy-batch --help
```

## 10. Depois da instalação

Confirme na Dashboard que cada Agent concluiu enrollment e ficou **Online**.

Quando um secret de senha não for mais necessário, remova-o:

```bash
sudo cap agent secret delete node-linux-01
sudo cap agent secret delete node-linux-02
sudo cap agent secret delete node-windows-01
```

A senha administrativa usada no bootstrap não é a credencial permanente do Agent.

## Diagnóstico rápido

### `Permission denied`

Verifique usuário, senha/chave e política de autenticação OpenSSH do host.

### `Connection refused` ou timeout

Confirme endereço, rota, firewall e se o OpenSSH Server está ouvindo na porta indicada.

### `password_file` rejeitado

Por padrão, o arquivo precisa ficar dentro de:

```text
/etc/capivara/secrets/remote-deploy
```

### `package_file must be inside ...`

O pacote está fora do diretório permitido. Por padrão use:

```text
/var/lib/capivara/agent-packages
```

Ou configure `DSM_AGENT_LOCAL_PACKAGE_DIR` para outro diretório administrativo controlado.

### `local Agent package not found`

Confirme o caminho do arquivo no **Controller**, não no host remoto.

### `invalid Linux Agent package`

O arquivo não é um pacote Linux válido do Capivara ou está corrompido. Gere novamente com `release/build_agent_package.sh` ou use um artefato oficial de release.

### Pacote local em Windows foi recusado

Esse comportamento é esperado no estado atual. O lote aceita pacote local somente para Linux.

### Host duplicado no CSV

Remova a duplicidade. A Dashboard não permite duas linhas com o mesmo host no mesmo lote.

### Um host falhou e os seguintes não foram executados

Use **Continuar em caso de erro** na Dashboard ou `--continue-on-error` na CLI.

## Segurança

- nunca armazene senha no CSV;
- nunca envie arquivos `.secret` ao Git;
- nunca exponha conteúdo de secrets em screenshots, tickets ou logs;
- prefira chave SSH quando possível;
- use arquivos de senha com permissão `0600`;
- armazene pacotes locais apenas em diretório administrativo controlado;
- não permita que usuários da Dashboard indiquem caminhos arbitrários fora do diretório autorizado;
- use somente pacotes oficiais cuja integridade possa ser validada;
- remova secrets temporários após o Agent ficar operacional;
- trate o CSV como arquivo administrativo de infraestrutura.

## Guias relacionados

- [Senha SSH em arquivo protegido](../authentication/ssh-password.md)
- [Bootstrap Linux por OpenSSH](../remote-deployment/linux-ssh.md)
- [Bootstrap Windows por OpenSSH](../remote-deployment/windows-ssh.md)
- [Instalação do Agent Linux](linux.md)
- [Instalação do Agent Windows](windows.md)
