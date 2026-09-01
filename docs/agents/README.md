# Capivara Agents — instalação e acesso remoto

Esta área documenta a preparação e instalação de Agents Linux e Windows.

## Guias

- [Instalação do Agent Linux](installation/linux.md)
- [Instalação do Agent Windows](installation/windows.md)
- [Instalação de Agents em lote](installation/batch.md) — inclui GitHub Release, proteção contra reexecução e pacote local Linux via `package_file`.
- [Bootstrap Linux por OpenSSH](remote-deployment/linux-ssh.md)
- [Bootstrap Windows por OpenSSH](remote-deployment/windows-ssh.md)
- [Senha SSH em arquivo protegido](authentication/ssh-password.md)

## Instalação em lote

A instalação em lote aceita hosts Linux e Windows no mesmo CSV.

Para Linux, o lote pode usar uma release publicada ou um pacote local já armazenado no Controller. Por padrão, pacotes locais autorizados ficam em:

```text
/var/lib/capivara/agent-packages
```

A coluna `package_file` é usada somente com `platform=linux` e `method=ssh`; ela não deve ser combinada com `release_tag` na mesma linha. O Controller valida o pacote e o transfere por SCP antes do bootstrap.

Pacote local em lote para Windows ainda não é suportado.

## Princípio de segurança

SSH é um transporte de bootstrap. Depois do enrollment e do primeiro heartbeat, o Agent usa sua identidade permanente e o protocolo Controller-Agent. O Controller não deve manter uma sessão administrativa permanente no host.

Chaves SSH são preferidas. Usuário + senha é suportado para sistemas recém-instalados através de `--password-file`; a senha nunca é aceita diretamente como argumento de `cap` nem como campo de senha da Dashboard.

Pacotes locais enviados pelo lote devem permanecer em diretório administrativo autorizado e são validados antes da transferência para o Agent.
