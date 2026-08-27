# Remote Agent OpenSSH Deployment

## Status

Architecture Decision — implemented for Linux and Windows bootstrap.

## Decision

O Controller do Capivara permanece Linux. OpenSSH é o transporte preferencial de bootstrap remoto para Agents Linux e Windows. WinRM HTTPS permanece como transporte alternativo para Windows em ambientes já preparados.

SSH não é o canal operacional permanente. Depois de enrollment e heartbeat confirmado, a comunicação normal utiliza a identidade e as credenciais do protocolo Controller-Agent.

## Interfaces

```text
cap agent test-connection HOST --platform linux|windows --ssh-user USER [options]
cap agent deploy HOST --platform linux|windows --ssh-user USER [options]
cap agent secret create NAME
cap agent secret delete NAME
```

Opções de autenticação:

```text
--identity-file PATH
--password-file PATH
```

São mutuamente exclusivas. Não existe e não deve existir `--password SENHA`.

## Sistemas recém-instalados

Um host novo pode possuir apenas IP/hostname, usuário administrativo e senha. Para esse cenário, o Controller aceita um arquivo protegido contendo somente a senha.

Diretório padrão:

```text
/etc/capivara/secrets/remote-deploy/
```

A forma recomendada de criação é:

```text
cap agent secret create NAME
```

A entrada é oculta, confirmada interativamente e o arquivo é criado com modo `0600`; o diretório usa `0700`. A Dashboard só aceita `password_file` dentro de `DSM_REMOTE_DEPLOY_SECRET_DIR`.

Quando `--password-file` é usado, o transporte local utiliza `sshpass -f ARQUIVO`. A senha não aparece no argv, no JSON ou nos logs. O caminho do arquivo não é considerado segredo. Chave SSH/ssh-agent continua sendo a autenticação preferencial.

## Preflight não destrutivo

`cap agent test-connection` e o botão **Testar conexão** da Dashboard não emitem pairing token e não instalam nada.

Linux valida:

- OpenSSH;
- autenticação;
- Linux;
- Bash;
- curl;
- Python 3;
- root ou `sudo -n`.

Windows valida:

- OpenSSH Server;
- autenticação;
- PowerShell;
- conta pertencente a Administrators;
- arquitetura.

## Bootstrap Linux

O Controller transmite um programa Python por stdin do SSH. Esse programa baixa `/agent/install.sh`, injeta o pairing token em variável de ambiente e executa o instalador. O pairing token não compõe o argv SSH.

## Bootstrap Windows

O Controller executa PowerShell por OpenSSH e transmite o bootstrap por stdin. O bootstrap baixa `/agent/install.ps1` e executa o instalador Windows. O pairing token não compõe o argv SSH remoto.

## Dashboard

A tela combinada foi substituída por:

```text
Adicionar Agent
├── Agent Linux
│   ├── GitHub Release
│   ├── Pacote local
│   └── OpenSSH
└── Agent Windows
    ├── GitHub Release
    ├── Pacote local
    ├── OpenSSH
    └── WinRM HTTPS
```

Cada assistente possui links de ajuda específicos para o sistema e para autenticação segura.

## Enrollment

O preflight ocorre antes da emissão do pairing token. Depois do preflight:

1. Controller emite pairing token de uso único e TTL curto.
2. bootstrap remoto instala o Agent.
3. Agent faz enrollment.
4. Controller vincula localização e pré-configuração.
5. Agent inicia heartbeat autenticado.
6. instalação só é considerada operacional após `active` + `online`.

Falhas de bootstrap expiram o pairing token não consumido.

## Segurança

1. Nunca aceitar senha diretamente no CLI ou payload da Dashboard.
2. Rejeitar password file com permissões para grupo/outros.
3. Não registrar conteúdo do secret.
4. Não imprimir pairing token ou credencial permanente.
5. Preservar host-key verification do OpenSSH.
6. Manter parâmetros em argv estruturado, sem `shell=True`.
7. Pairing token deve viajar no stdin/bootstrap, não no argv remoto.
8. SSH termina como dependência administrativa depois do bootstrap.
9. O Agent nunca persiste a senha administrativa do host.

## Documentação operacional

- `docs/agents/installation/linux.md`
- `docs/agents/installation/windows.md`
- `docs/agents/remote-deployment/linux-ssh.md`
- `docs/agents/remote-deployment/windows-ssh.md`
- `docs/agents/authentication/ssh-password.md`
