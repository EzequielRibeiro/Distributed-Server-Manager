# Senha SSH em arquivo protegido

Use este fluxo somente quando o host ainda não possui uma chave SSH preparada, cenário comum em sistemas recém-instalados. Chaves SSH continuam sendo o método preferencial.

## Criar o arquivo pelo Capivara

No Controller Linux:

```bash
sudo cap agent secret create node01
```

O comando pede a senha duas vezes usando entrada oculta. A senha não é recebida como argumento de CLI e, portanto, não entra no histórico do shell.

Por padrão o arquivo é criado em:

```text
/etc/capivara/secrets/remote-deploy/node01.secret
```

com diretório `0700` e arquivo `0600`.

O conteúdo do arquivo é somente a senha, seguida por quebra de linha. Não use JSON, `PASSWORD=`, aspas ou comentários.

## Testar a senha SSH diretamente

Antes de usar o deploy do Capivara, é possível confirmar se a senha armazenada no arquivo realmente autentica no host remoto.

Linux:

```bash
sudo sshpass \
  -f /etc/capivara/secrets/remote-deploy/node01.secret \
  ssh \
  -p 22 \
  -o ConnectTimeout=10 \
  -o BatchMode=no \
  -o PreferredAuthentications=password \
  USER@HOST \
  'echo CAPIVARA_SSH_OK; id'
```

Exemplo:

```bash
sudo sshpass \
  -f /etc/capivara/secrets/remote-deploy/node01.secret \
  ssh \
  -p 22 \
  -o ConnectTimeout=10 \
  -o BatchMode=no \
  -o PreferredAuthentications=password \
  USER@192.168.15.59 \
  'echo CAPIVARA_SSH_OK; id'
```

Resultado esperado:

```text
CAPIVARA_SSH_OK
uid=...(...)
```

Se retornar `Permission denied`, a rede e o serviço SSH podem estar acessíveis, mas a senha foi rejeitada ou o usuário não permite autenticação por senha. Em servidores Linux, não habilite login SSH de `root` apenas para o Capivara; prefira um usuário administrativo com `sudo`.

## Testar a conexão pelo Capivara antes de instalar

Linux:

```bash
sudo cap agent test-connection 192.168.15.59 \
  --platform linux \
  --ssh-user USER \
  --password-file /etc/capivara/secrets/remote-deploy/node01.secret
```

Resultado esperado:

```text
Capivara Agent Connection Test

Host.............. 192.168.15.59:22
SSH............... OK
Platform.......... linux
Architecture...... x86_64
Authentication.... password-file
Privilege......... sudo-password
Ready............. YES
```

Windows:

```bash
sudo cap agent test-connection 192.168.1.60 \
  --platform windows \
  --ssh-user Administrator \
  --password-file /etc/capivara/secrets/remote-deploy/win-node01.secret
```

O teste é não destrutivo: valida transporte, autenticação, plataforma e privilégios, sem emitir pairing token ou instalar Agent.

## Instalar

```bash
sudo cap agent deploy HOST \
  --platform linux \
  --ssh-user USER \
  --password-file /etc/capivara/secrets/remote-deploy/node01.secret
```

Use `--platform windows` para um Agent Windows.

A implementação usa `sshpass -f ARQUIVO` quando `--password-file` é escolhido. O caminho do arquivo pode aparecer no processo; a senha não. `sshpass` precisa estar instalado no Controller para esse modo. Sem `--password-file`, o OpenSSH usa chave/ssh-agent e `sshpass` não é necessário.

## Depois do bootstrap

Assim que o Agent fizer enrollment e estiver online, remova o secret se ele não for mais necessário:

```bash
sudo cap agent secret delete node01
```

A credencial administrativa do host não é copiada para a configuração permanente do Agent.

## Regras

- Nunca use `--password SENHA`.
- Nunca grave a senha em Git.
- Não use arquivo com permissões de grupo/outros; o Capivara rejeita permissões mais abertas que `0600`.
- A Dashboard aceita somente caminhos dentro de `DSM_REMOTE_DEPLOY_SECRET_DIR`, que por padrão é `/etc/capivara/secrets/remote-deploy`.
- Não registrar conteúdo do secret, pairing token ou credencial permanente em logs ou JSON de saída.
