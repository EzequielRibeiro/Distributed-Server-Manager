# Senha SSH em arquivo protegido

Use este fluxo somente quando o host ainda não possui uma chave SSH preparada, cenário comum em sistemas recém-instalados. Chaves SSH continuam sendo o método preferencial.

## Criar o arquivo pelo Capivara

No Controller Linux:

```bash
cap agent secret create node01
```

O comando pede a senha duas vezes usando entrada oculta. A senha não é recebida como argumento de CLI e, portanto, não entra no histórico do shell.

Por padrão o arquivo é criado em:

```text
/etc/capivara/secrets/remote-deploy/node01.secret
```

com diretório `0700` e arquivo `0600`.

O conteúdo do arquivo é somente a senha, seguida por quebra de linha. Não use JSON, `PASSWORD=`, aspas ou comentários.

## Testar antes de instalar

Linux:

```bash
cap agent test-connection 192.168.1.50 \
  --platform linux \
  --ssh-user root \
  --password-file /etc/capivara/secrets/remote-deploy/node01.secret
```

Windows:

```bash
cap agent test-connection 192.168.1.60 \
  --platform windows \
  --ssh-user Administrator \
  --password-file /etc/capivara/secrets/remote-deploy/win-node01.secret
```

O teste é não destrutivo: valida transporte, autenticação, plataforma e privilégios, sem emitir pairing token ou instalar Agent.

## Instalar

```bash
cap agent deploy HOST \
  --platform linux \
  --ssh-user root \
  --password-file /etc/capivara/secrets/remote-deploy/node01.secret
```

Use `--platform windows` para um Agent Windows.

A implementação usa `sshpass -f ARQUIVO` quando `--password-file` é escolhido. O caminho do arquivo pode aparecer no processo; a senha não. `sshpass` precisa estar instalado no Controller para esse modo. Sem `--password-file`, o OpenSSH usa chave/ssh-agent e `sshpass` não é necessário.

## Depois do bootstrap

Assim que o Agent fizer enrollment e estiver online, remova o secret se ele não for mais necessário:

```bash
cap agent secret delete node01
```

A credencial administrativa do host não é copiada para a configuração permanente do Agent.

## Regras

- Nunca use `--password SENHA`.
- Nunca grave a senha em Git.
- Não use arquivo com permissões de grupo/outros; o Capivara rejeita permissões mais abertas que `0600`.
- A Dashboard aceita somente caminhos dentro de `DSM_REMOTE_DEPLOY_SECRET_DIR`, que por padrão é `/etc/capivara/secrets/remote-deploy`.
- Não registrar conteúdo do secret, pairing token ou credencial permanente em logs ou JSON de saída.
