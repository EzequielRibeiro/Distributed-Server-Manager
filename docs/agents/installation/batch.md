# Instalação de Agents em lote

Este guia mostra como instalar vários Capivara Agents a partir de um único arquivo CSV, incluindo hosts **Linux e Windows no mesmo lote**.

O fluxo recomendado usa **OpenSSH para as duas plataformas**. Isso permite utilizar o mesmo mecanismo seguro de autenticação por chave SSH ou por arquivo de senha protegido (`password_file`) tanto em Linux quanto em Windows.

> A senha do usuário remoto nunca deve ser escrita diretamente no CSV. O CSV contém somente o caminho para um arquivo secreto protegido existente no Controller.

## Pré-requisitos

No Controller ou instalação Hybrid:

- `cap agent deploy-batch` disponível;
- conectividade TCP do Controller até a porta SSH dos hosts;
- OpenSSH Server ativo nos hosts Linux e Windows;
- usuário remoto com privilégios administrativos suficientes para instalar o Agent;
- região, datacenter e Controller já cadastrados quando esses campos forem usados pela Dashboard;
- `sshpass` instalado no Controller caso seja utilizada autenticação por `password_file`.

Para Windows em lote, este guia usa **OpenSSH**. O usuário pode ser, por exemplo, `Administrator` ou outra conta administrativa permitida pelo host.

## 1. Criar os arquivos secretos de senha

Crie um secret separado para cada senha/host quando as credenciais forem diferentes.

No Controller:

```bash
sudo cap agent secret create node-linux-01
sudo cap agent secret create node-linux-02
sudo cap agent secret create node-windows-01
sudo cap agent secret create node-windows-02
```

O Capivara solicita a senha duas vezes usando entrada oculta. A senha não é passada como argumento e não fica registrada no histórico do shell.

Por padrão, os arquivos serão criados em:

```text
/etc/capivara/secrets/remote-deploy/node-linux-01.secret
/etc/capivara/secrets/remote-deploy/node-linux-02.secret
/etc/capivara/secrets/remote-deploy/node-windows-01.secret
/etc/capivara/secrets/remote-deploy/node-windows-02.secret
```

O diretório deve permanecer protegido e os arquivos de segredo devem usar permissão `0600`.

Confira sem exibir o conteúdo:

```bash
sudo ls -l /etc/capivara/secrets/remote-deploy/
```

Nunca use `cat` para mostrar a senha durante diagnóstico ou documentação.

### Mesmo usuário e mesma senha em vários hosts

Tecnicamente várias linhas podem apontar para o mesmo `password_file` quando os hosts realmente utilizam a mesma credencial. Por segurança, prefira credenciais individuais por host ou por grupo administrativo controlado.

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

## 3. Criar o arquivo CSV

Crie, por exemplo:

```bash
nano ~/capivara-agents.csv
```

Exemplo com **dois hosts Linux e dois hosts Windows no mesmo arquivo**:

```csv
host,ssh_user,platform,ssh_port,password_file,controller_id,controller_url,region_id,datacenter_id,name,port_range,port_protocol,release_tag,bootstrap_timeout
192.168.15.60,capadmin,linux,22,/etc/capivara/secrets/remote-deploy/node-linux-01.secret,controller-horizon,https://controller.capivaradsm.com.br:9443,br,sp01,Node Linux 01,24000-24999,both,,900
192.168.15.61,capadmin,linux,22,/etc/capivara/secrets/remote-deploy/node-linux-02.secret,controller-horizon,https://controller.capivaradsm.com.br:9443,br,sp01,Node Linux 02,25000-25999,both,,900
192.168.15.70,Administrator,windows,22,/etc/capivara/secrets/remote-deploy/node-windows-01.secret,controller-horizon,https://controller.capivaradsm.com.br:9443,br,sp01,Node Windows 01,26000-26999,both,,900
192.168.15.71,Administrator,windows,22,/etc/capivara/secrets/remote-deploy/node-windows-02.secret,controller-horizon,https://controller.capivaradsm.com.br:9443,br,sp01,Node Windows 02,27000-27999,both,,900
```

Substitua os valores de exemplo pelos IDs e endereços reais do seu ambiente.

### Campos mais importantes

| Campo | Uso |
|---|---|
| `host` | IP ou hostname alcançável pelo Controller. Obrigatório. |
| `ssh_user` | Usuário usado pelo OpenSSH. Obrigatório. |
| `platform` | `linux` ou `windows`. Se omitido, o padrão do CLI é `linux`. |
| `ssh_port` | Porta do OpenSSH. O padrão é `22`. |
| `password_file` | Caminho do secret protegido no Controller. Nunca coloque a senha aqui. |
| `controller_id` | ID lógico do Controller que receberá o Agent. Na Dashboard administrativa, informe explicitamente. |
| `controller_url` | URL que o Agent usará para alcançar o Controller após o bootstrap. |
| `region_id` | Região administrativa do Agent. |
| `datacenter_id` | Datacenter administrativo do Agent. |
| `name` | Nome amigável do Agent. |
| `port_range` | Faixa reservada para instâncias, por exemplo `24000-24999`. |
| `port_protocol` | `tcp`, `udp` ou `both`. |
| `release_tag` | Release específica. Em branco, a Dashboard seleciona a release estável recomendada. |
| `bootstrap_timeout` | Timeout do bootstrap em segundos. Exemplo: `900`. |

## 4. Regras do CSV

Para manter compatibilidade com o fluxo oficial de lote:

- `host` e `ssh_user` são colunas obrigatórias;
- `platform` aceita somente `linux` ou `windows`;
- `port_protocol` aceita somente `tcp`, `udp` ou `both`;
- não adicione uma coluna `password`;
- não adicione `ssh_password` ou senha em texto puro;
- use `password_file` para autenticação por senha;
- o caminho informado em `password_file` precisa existir no **Controller**, não no host remoto;
- mantenha uma linha por Agent;
- não reutilize a mesma faixa de portas entre Agents quando isso causar conflito com sua política de placement.

O CLI também aceita campos avançados como `identity_file`, `package_file`, `pairing_ttl`, `connect_timeout` e `heartbeat_timeout`. Consulte:

```bash
cap agent deploy-batch --help
```

## 5. Instalar pela Dashboard

Na Dashboard administrativa:

1. abra **Agents**;
2. escolha **Adicionar Agent**;
3. escolha **Agents em lote**;
4. selecione o arquivo `.csv`;
5. opcionalmente marque **Continuar em caso de erro**;
6. inicie **Instalar Agents em lote**;
7. acompanhe o resultado de cada linha.

A Dashboard envia cada host sequencialmente pelo fluxo normal de instalação. Uma falha em um host não transforma a senha em dado de formulário: somente o caminho do `password_file` é enviado ao backend.

## 6. Instalar pela CLI

O mesmo CSV pode ser executado diretamente no Controller:

```bash
sudo cap agent deploy-batch ~/capivara-agents.csv
```

Por padrão, o processamento para na primeira falha.

Para continuar com as linhas seguintes:

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

O resumo informa quantas linhas foram processadas, concluídas e falharam.

## 7. Exemplo usando chave SSH em alguns hosts e senha em outros

O lote não obriga todos os hosts a usar o mesmo método de autenticação OpenSSH.

Quando a identidade SSH do Controller já estiver configurada para determinado host, deixe `password_file` vazio nessa linha:

```csv
host,ssh_user,platform,ssh_port,password_file,controller_id,controller_url,region_id,datacenter_id,name,port_range,port_protocol
192.168.15.60,capadmin,linux,22,,controller-horizon,https://controller.capivaradsm.com.br:9443,br,sp01,Linux com chave,24000-24999,both
192.168.15.70,Administrator,windows,22,/etc/capivara/secrets/remote-deploy/node-windows-01.secret,controller-horizon,https://controller.capivaradsm.com.br:9443,br,sp01,Windows com senha protegida,26000-26999,both
```

Chaves SSH continuam sendo o método preferencial.

## 8. Depois da instalação

Confirme na Dashboard que os Agents fizeram enrollment e estão Online.

Quando um secret de senha não for mais necessário, remova-o:

```bash
sudo cap agent secret delete node-linux-01
sudo cap agent secret delete node-linux-02
sudo cap agent secret delete node-windows-01
sudo cap agent secret delete node-windows-02
```

A senha administrativa usada no bootstrap não é a credencial permanente do Agent.

## Diagnóstico rápido

### `Permission denied`

Verifique usuário, senha/chave e política de autenticação OpenSSH do host.

### `Connection refused` ou timeout

Confirme endereço, rota, firewall e se o OpenSSH Server está ouvindo na porta indicada em `ssh_port`.

### Windows não aceita SSH

Confirme que o OpenSSH Server está instalado, iniciado e permitido no firewall do Windows antes de executar o lote.

### `password_file` rejeitado

O arquivo precisa existir no Controller e, no fluxo da Dashboard, deve estar dentro do diretório autorizado de secrets, cujo padrão é:

```text
/etc/capivara/secrets/remote-deploy
```

### Um host falhou e os seguintes não foram executados

Use **Continuar em caso de erro** na Dashboard ou `--continue-on-error` na CLI.

## Segurança

- Nunca armazene senha no CSV.
- Nunca envie arquivos `.secret` ao Git.
- Nunca exponha conteúdo de secrets em screenshots, tickets ou logs.
- Prefira chave SSH quando possível.
- Use arquivos de senha com permissão `0600`.
- Remova secrets temporários após o Agent ficar operacional.
- O CSV pode conter informações de infraestrutura; trate-o como arquivo administrativo e remova-o quando não for mais necessário.

## Guias relacionados

- [Senha SSH em arquivo protegido](../authentication/ssh-password.md)
- [Bootstrap Linux por OpenSSH](../remote-deployment/linux-ssh.md)
- [Bootstrap Windows por OpenSSH](../remote-deployment/windows-ssh.md)
- [Instalação do Agent Linux](linux.md)
- [Instalação do Agent Windows](windows.md)
