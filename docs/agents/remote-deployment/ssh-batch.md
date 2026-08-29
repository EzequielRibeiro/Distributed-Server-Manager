# Instalação remota de Agents por SSH — individual e em lote

Este documento descreve o bootstrap remoto de Agents Capivara por OpenSSH a partir de um Controller ou instalação Hybrid. O mesmo modelo é usado pela CLI `cap` e pela Dashboard.

## Modelo de segurança

O Capivara oferece dois métodos independentes de autenticação SSH:

- **Senha protegida**: a senha fica em um arquivo local do Controller com permissão `0600` ou mais restritiva. A senha não é aceita como argumento de linha de comando e não deve aparecer no CSV.
- **Chave SSH**: a chave privada fica somente no Controller. A chave pública correspondente é instalada no `authorized_keys` do usuário do host destino.

Não há conversão obrigatória de senha em chave. O administrador escolhe um dos dois métodos para cada implantação.

O bootstrap SSH é uma operação administrativa de Controller/Hybrid. O transporte mantém a política de host key do Capivara (`StrictHostKeyChecking=accept-new`): uma chave de host nova pode ser registrada, mas uma alteração posterior da chave é tratada como falha.

## 1. Autenticação por senha

Crie o secret usando a CLI administrativa quando disponível:

```bash
sudo cap agent secret create dc-sp
```

O arquivo deve ficar no diretório autorizado de implantação remota, por padrão:

```text
/etc/capivara/secrets/remote-deploy/
```

Exemplo de arquivo:

```text
/etc/capivara/secrets/remote-deploy/dc-sp.secret
```

O conteúdo é somente a senha SSH, seguido opcionalmente por uma quebra de linha. Não coloque `usuario=`, JSON ou YAML no arquivo. Confirme que apenas o proprietário pode lê-lo:

```bash
sudo chmod 600 /etc/capivara/secrets/remote-deploy/dc-sp.secret
```

Autenticação por senha requer `sshpass` no Controller.

## 2. Autenticação por chave SSH

Gere o par de chaves no **Controller**, não no host destino:

```bash
sudo install -d -m 700 /etc/capivara/ssh/remote-deploy
sudo ssh-keygen -t ed25519 \
  -f /etc/capivara/ssh/remote-deploy/dc-sp.key \
  -C capivara-agent-deploy
sudo chmod 600 /etc/capivara/ssh/remote-deploy/dc-sp.key
```

São criados:

```text
/etc/capivara/ssh/remote-deploy/dc-sp.key      # privada — permanece no Controller
/etc/capivara/ssh/remote-deploy/dc-sp.key.pub  # pública — pode ser distribuída
```

Instale somente a chave pública no `authorized_keys` do usuário administrativo de cada host destino. O Capivara nunca precisa copiar a chave privada para um Agent.

A Dashboard aceita chaves somente dentro de `/etc/capivara/ssh/remote-deploy` por padrão. O diretório pode ser alterado pelo administrador com `DSM_REMOTE_DEPLOY_IDENTITY_DIR`.

## 3. Teste de conexão individual

Com senha protegida:

```bash
cap agent test-connection 192.168.15.51 \
  --ssh-user admin \
  --password-file /etc/capivara/secrets/remote-deploy/dc-sp.secret
```

Com chave SSH:

```bash
cap agent test-connection 192.168.15.51 \
  --ssh-user admin \
  --identity-file /etc/capivara/ssh/remote-deploy/dc-sp.key
```

Para Windows com OpenSSH Server:

```bash
cap agent test-connection win-node01.example \
  --platform windows \
  --ssh-user Administrator \
  --identity-file /etc/capivara/ssh/remote-deploy/windows-dc.key
```

## 4. Instalação individual

Com senha:

```bash
cap agent deploy 192.168.15.51 \
  --ssh-user admin \
  --password-file /etc/capivara/secrets/remote-deploy/dc-sp.secret \
  --region-id br-sp \
  --datacenter-id dc-sp-01
```

Com chave:

```bash
cap agent deploy 192.168.15.51 \
  --ssh-user admin \
  --identity-file /etc/capivara/ssh/remote-deploy/dc-sp.key \
  --region-id br-sp \
  --datacenter-id dc-sp-01
```

## 5. Arquivo CSV para lote

O CSV usa UTF-8 e deve possuir cabeçalho. O formato mínimo é:

```csv
host,name,user,port
192.168.15.51,Node-SP-01,admin,22
192.168.15.52,Node-SP-02,admin,22
192.168.15.53,Node-SP-03,admin,22
```

`user` e `port` podem ser omitidos por linha quando foram informados globalmente na CLI:

```csv
host,name
192.168.15.51,Node-SP-01
192.168.15.52,Node-SP-02
192.168.15.53,Node-SP-03
```

Campos reconhecidos pela CLI:

| Campo | Descrição |
|---|---|
| `host` | IPv4, IPv6 ou hostname. Obrigatório. |
| `name` | Nome administrativo desejado para o Agent. |
| `user` / `ssh_user` | Usuário SSH. Sobrescreve `--ssh-user`. |
| `port` / `ssh_port` | Porta SSH. Sobrescreve `--ssh-port`. |
| `platform` | `linux` ou `windows`. |
| `region` / `region_id` | Região do Agent. |
| `datacenter` / `datacenter_id` | Datacenter do Agent. |
| `password_file` | Caminho local do Controller para o secret dessa linha. |
| `identity_file` | Caminho local do Controller para a chave privada dessa linha. |

Uma linha nunca pode definir `password_file` e `identity_file` simultaneamente. Colunas `password` e `ssh_password` são recusadas propositalmente: senhas em texto puro não pertencem ao CSV.

Exemplo avançado, misturando credenciais por host:

```csv
host,name,user,port,platform,region,datacenter,password_file,identity_file
192.168.15.51,Node-SP-01,admin,22,linux,br-sp,dc-sp-01,/etc/capivara/secrets/remote-deploy/dc-sp.secret,
192.168.15.52,Node-SP-02,admin,22,linux,br-sp,dc-sp-01,/etc/capivara/secrets/remote-deploy/dc-sp.secret,
10.20.0.31,Node-SE-01,deploy,22,linux,br-se,dc-se-01,,/etc/capivara/ssh/remote-deploy/dc-se.key
```

## 6. Teste em lote

Mesma senha para todos os hosts:

```bash
cap agent test-connection \
  --hosts-file hosts.csv \
  --ssh-user admin \
  --password-file /etc/capivara/secrets/remote-deploy/dc-sp.secret
```

Mesma chave para todos:

```bash
cap agent test-connection \
  --hosts-file hosts.csv \
  --ssh-user admin \
  --identity-file /etc/capivara/ssh/remote-deploy/dc-sp.key
```

Controle de paralelismo:

```bash
cap agent test-connection --hosts-file hosts.csv --ssh-user admin \
  --identity-file /etc/capivara/ssh/remote-deploy/dc-sp.key \
  --concurrency 10
```

O limite atual é 20 operações concorrentes e 500 hosts por lote.

Saída JSON para automação:

```bash
cap agent test-connection --hosts-file hosts.csv --ssh-user admin \
  --identity-file /etc/capivara/ssh/remote-deploy/dc-sp.key --json
```

Estrutura resumida:

```json
{
  "ok": false,
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "targets": [
    {"host": "192.168.15.51", "status": "reachable", "ok": true},
    {"host": "192.168.15.52", "status": "reachable", "ok": true},
    {"host": "192.168.15.53", "status": "failed", "ok": false, "error": "..."}
  ]
}
```

## 7. Instalação em lote

Com senha:

```bash
cap agent deploy \
  --hosts-file hosts.csv \
  --ssh-user admin \
  --password-file /etc/capivara/secrets/remote-deploy/dc-sp.secret \
  --region-id br-sp \
  --datacenter-id dc-sp-01 \
  --concurrency 5
```

Com chave:

```bash
cap agent deploy \
  --hosts-file hosts.csv \
  --ssh-user admin \
  --identity-file /etc/capivara/ssh/remote-deploy/dc-sp.key \
  --region-id br-sp \
  --datacenter-id dc-sp-01 \
  --concurrency 5
```

Cada destino é independente. Uma falha não cancela os outros hosts e a saída mantém a ordem do CSV. Em lote, código de saída `0` significa sucesso de todos os hosts, `3` significa que um ou mais hosts falharam e `2` indica erro de entrada/configuração. O modo individual mantém `0` para sucesso e `2` para falha.

## 8. Dashboard

Em **Agents → Adicionar Agent → Linux/Windows → Instalar remotamente via OpenSSH**, o fluxo é:

1. escolha **Host único** ou **Instalação em lote**;
2. escolha **Senha protegida** ou **Chave SSH**;
3. informe o caminho protegido da credencial no Controller;
4. no lote, cole a lista CSV ou importe um arquivo `.csv`;
5. clique em **Testar todos**;
6. somente hosts aprovados no preflight entram na instalação;
7. acompanhe o resultado individual de cada host.

Na importação pela Dashboard, o CSV deve conter somente metadados dos hosts (`host,name,user,port,platform`). A credencial é selecionada separadamente na própria Dashboard e não deve ser embutida no arquivo enviado pelo navegador.

## 9. Boas práticas

- Prefira chave SSH quando o datacenter já suporta provisionamento de chaves públicas.
- Use senha protegida para máquinas recém-instaladas quando esse for o único acesso inicial disponível.
- Nunca reutilize uma chave privada de usuário pessoal como chave de implantação do Capivara.
- Crie chaves específicas por ambiente/datacenter quando possível.
- Revogue a chave pública nos hosts quando uma chave privada for substituída.
- Não envie secrets por e-mail, tickets, CSV ou parâmetros de processo.
- Teste o lote antes da implantação e use concorrência moderada para não sobrecarregar Controller, rede ou bastion.
