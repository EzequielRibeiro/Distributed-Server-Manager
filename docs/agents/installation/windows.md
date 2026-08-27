# Instalação do Agent Windows

A Dashboard possui uma tela exclusiva para Windows: **Adicionar Agent → Agent Windows**.

## Métodos disponíveis

1. GitHub Release — gera a instrução PowerShell oficial.
2. Pacote local — gera a instrução para o instalador já disponível.
3. OpenSSH — transporte remoto preferencial para novas instalações.
4. WinRM HTTPS — compatibilidade para ambientes já preparados com certificado.

## OpenSSH Server

O host Windows precisa possuir OpenSSH Server instalado, serviço `sshd` ativo, porta liberada no firewall e uma conta com privilégios de Administrador. PowerShell também é obrigatório.

Valide antes de instalar:

```bash
cap agent test-connection HOST \
  --platform windows \
  --ssh-user Administrator
```

Em máquina recém-instalada que ainda só possui usuário + senha, use o [arquivo de senha protegido](../authentication/ssh-password.md).

## Bootstrap

```bash
cap agent deploy HOST \
  --platform windows \
  --ssh-user Administrator
```

O Controller envia o script de bootstrap pelo stdin do OpenSSH para evitar colocar o pairing token na linha de comando remota. Depois do enrollment, a comunicação normal usa a identidade permanente do Agent.

Consulte também [Bootstrap Windows por OpenSSH](../remote-deployment/windows-ssh.md).
