# Capivara Agents — instalação e acesso remoto

Esta área documenta a preparação e instalação de Agents Linux e Windows.

## Guias

- [Instalação do Agent Linux](installation/linux.md)
- [Instalação do Agent Windows](installation/windows.md)
- [Instalação de Agents em lote](installation/batch.md)
- [Bootstrap Linux por OpenSSH](remote-deployment/linux-ssh.md)
- [Bootstrap Windows por OpenSSH](remote-deployment/windows-ssh.md)
- [Senha SSH em arquivo protegido](authentication/ssh-password.md)

## Princípio de segurança

SSH é um transporte de bootstrap. Depois do enrollment e do primeiro heartbeat, o Agent usa sua identidade permanente e o protocolo Controller-Agent. O Controller não deve manter uma sessão administrativa permanente no host.

Chaves SSH são preferidas. Usuário + senha é suportado para sistemas recém-instalados através de `--password-file`; a senha nunca é aceita diretamente como argumento de `cap` nem como campo de senha da Dashboard.
