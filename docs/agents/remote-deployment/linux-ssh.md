# Bootstrap remoto do Agent Linux por OpenSSH

## Fluxo

Controller Linux → OpenSSH → host Linux → installer → enrollment → heartbeat → protocolo Controller-Agent.

SSH é usado somente para bootstrap.

## Pré-requisitos do destino

- OpenSSH Server acessível.
- Bash.
- curl.
- Python 3.
- usuário `root` ou usuário com `sudo -n` habilitado para o bootstrap.
- saída HTTP/HTTPS até a URL do Controller.

## Autenticação

Preferencialmente use chave SSH/ssh-agent. Para host recém-instalado sem chave provisionada, use `--password-file`; consulte [Senha SSH em arquivo protegido](../authentication/ssh-password.md).

## Diagnóstico

```bash
cap agent test-connection HOST --platform linux --ssh-user USER
```

O diagnóstico é somente leitura e não gera pairing token.

## Instalação

```bash
cap agent deploy HOST --platform linux --ssh-user USER
```

Opções relevantes:

```text
--ssh-port PORT
--identity-file PATH
--password-file PATH
--controller-url URL
--region-id ID
--datacenter-id ID
--name NAME
--release-tag TAG
--json
```

`--identity-file` e `--password-file` são mutuamente exclusivos. Não existe opção `--password`.
