# Bootstrap remoto do Agent Windows por OpenSSH

O OpenSSH passa a ser o transporte preferencial para novas instalações remotas de Agent Windows. WinRM HTTPS continua disponível para ambientes que já o utilizam.

## Preparar o Windows

O host deve possuir:

- Windows suportado pelo Agent;
- OpenSSH Server instalado;
- serviço `sshd` ativo e configurado para iniciar com o sistema;
- regra de firewall permitindo a porta SSH escolhida, normalmente TCP/22;
- PowerShell;
- conta usada no bootstrap pertencente ao grupo Administrators;
- acesso de saída HTTP/HTTPS até o Controller.

A instalação remota não requer que o Controller seja Windows: o Controller permanece Linux e utiliza o cliente OpenSSH para acessar o host Windows.

## Testar acesso

```bash
cap agent test-connection HOST \
  --platform windows \
  --ssh-user Administrator
```

Com senha temporária de um sistema recém-instalado:

```bash
cap agent secret create win-node01
cap agent test-connection HOST \
  --platform windows \
  --ssh-user Administrator \
  --password-file /etc/capivara/secrets/remote-deploy/win-node01.secret
```

O preflight confirma que a conexão SSH funciona, que PowerShell está disponível e que a conta possui privilégios de Administrador.

## Instalar

```bash
cap agent deploy HOST \
  --platform windows \
  --ssh-user Administrator
```

O bootstrap PowerShell é transmitido pelo stdin do SSH. O pairing token não precisa compor a linha de comando do processo remoto.

Após enrollment e heartbeat, SSH deixa de ser o canal normal de administração do Agent.
