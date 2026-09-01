# Instalação do Agent Linux

A Dashboard possui uma tela exclusiva para Linux: **Adicionar Agent → Agent Linux**.

## Métodos disponíveis

1. GitHub Release — gera a instrução oficial usando uma release publicada.
2. Pacote local — gera a instrução para um pacote já disponível no host.
3. OpenSSH — o Controller faz preflight e bootstrap remotamente.
4. Lote por CSV — vários hosts Linux podem ser instalados por GitHub Release ou por um pacote local armazenado no Controller.

## OpenSSH

Informe host/IP, usuário, porta e a URL do Controller que o próprio Agent conseguirá alcançar. A porta SSH padrão é 22.

Autenticação preferida: chave SSH ou ssh-agent. Em host recém-instalado, pode ser usado um [arquivo de senha protegido](../authentication/ssh-password.md).

Antes do deploy, use o botão **Testar conexão SSH** ou:

```bash
cap agent test-connection HOST --platform linux --ssh-user USER
```

O preflight confirma Linux, Bash, curl, Python 3 e privilégios administrativos. Com chave SSH, um usuário não-root precisa possuir `sudo -n`. Quando `--password-file` é usado em um sistema recém-instalado, o Capivara utiliza a mesma credencial pelo stdin para validar e executar `sudo -S`; a senha não entra no argv nem nos logs. O teste não instala nada.

## Bootstrap por release

```bash
cap agent deploy HOST --platform linux --ssh-user USER
```

Em um host recém-instalado que usa a mesma senha para SSH e sudo:

```bash
cap agent deploy HOST \
  --platform linux \
  --ssh-user USER \
  --password-file /etc/capivara/secrets/remote-deploy/node01.secret
```

## Pacote local em instalação em lote

A Dashboard de lote também pode usar um pacote Linux existente no **Controller**. O pacote não é enviado pelo navegador: o CSV informa o caminho administrativo em `package_file`, e o Controller valida e transfere o arquivo por SCP.

Diretório padrão autorizado:

```text
/var/lib/capivara/agent-packages
```

Exemplo:

```text
/var/lib/capivara/agent-packages/capivara-agent-linux-2.0.20.tar.gz
```

O diretório pode ser alterado com `DSM_AGENT_LOCAL_PACKAGE_DIR`.

No CSV use:

```text
platform=linux
method=ssh
package_file=/var/lib/capivara/agent-packages/capivara-agent-linux-2.0.20.tar.gz
release_tag=
```

`package_file` e `release_tag` não devem ser usados juntos.

Antes do bootstrap, o Controller verifica que o pacote está dentro do diretório autorizado, valida `manifest.json`, `VERSION`, arquivos obrigatórios, tamanho e SHA-256, executa o preflight SSH e recusa reinstalação automática quando já detecta um Agent no destino.

Consulte o guia completo: [Instalação de Agents em lote](batch.md).

Após o bootstrap, o Controller só considera a instalação concluída quando pairing, identidade do Agent e heartbeat forem confirmados. SSH deixa de ser o canal operacional normal.
