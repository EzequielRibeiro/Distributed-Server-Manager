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

O preflight confirma Linux, Bash, curl, Python 3 e privilégios de root ou `sudo -n`. O teste não instala nada.

## Bootstrap

```bash
cap agent deploy HOST --platform linux --ssh-user USER
```

Após o bootstrap, o Controller só considera a instalação concluída quando pairing, identidade do Agent e heartbeat forem confirmados. SSH deixa de ser o canal operacional normal.
