# Instalação do Agent Linux

A Dashboard possui uma tela exclusiva para Linux: **Adicionar Agent → Agent Linux**.

## Métodos disponíveis

1. GitHub Release — gera a instrução oficial usando uma release publicada.
2. Pacote local — gera a instrução para um pacote já disponível no host.
3. OpenSSH — o Controller faz preflight e bootstrap remotamente.

## OpenSSH

Informe host/IP, usuário, porta e a URL do Controller que o próprio Agent conseguirá alcançar. A porta SSH padrão é 22.

Autenticação preferida: chave SSH ou ssh-agent. Em host recém-instalado, pode ser usado um [arquivo de senha protegido](../authentication/ssh-password.md).

Antes do deploy, use o botão **Testar conexão SSH** ou:

```bash
cap agent test-connection HOST --platform linux --ssh-user USER
```

O preflight confirma Linux, Bash, curl, Python 3 e privilégios administrativos. Com chave SSH, um usuário não-root precisa possuir `sudo -n`. Quando `--password-file` é usado em um sistema recém-instalado, o Capivara utiliza a mesma credencial pelo stdin para validar e executar `sudo -S`; a senha não entra no argv nem nos logs. O teste não instala nada.

## Bootstrap

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

Após o bootstrap, o Controller só considera a instalação concluída quando pairing, identidade do Agent e heartbeat forem confirmados. SSH deixa de ser o canal operacional normal.
