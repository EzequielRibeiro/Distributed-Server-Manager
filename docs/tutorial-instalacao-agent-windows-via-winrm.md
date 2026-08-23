# Tutorial — instalação remota do Agent Windows via WinRM

## Resultado

Depois de uma preparação única, a Dashboard instala e atualiza o Agent Windows sem solicitar senha. O Controller autentica com certificado de cliente e o token de enrollment continua de uso único.

## 1. Pré-requisitos no Windows

Abra o PowerShell como Administrador e habilite o acesso remoto HTTPS conforme a política de certificados da organização. A porta padrão é `5986`; não exponha WinRM diretamente à Internet. Libere-a somente entre o Controller e o Agent.

Para um laboratório, o repositório contém `agents/windows/installer/enable-winrm-https.ps1`. Copie-o para o Windows e execute indicando o IP do Controller:

```powershell
.\enable-winrm-https.ps1 -ControllerAddress '192.168.15.35'
```

O nome usado pelo Controller deve coincidir com o certificado HTTPS do Windows. Em laboratório, `--insecure` permite certificado não confiável, mas não deve ser usado em produção.

## 2. Preparar o Controller

Instale a dependência opcional:

```bash
sudo python3 -m pip install 'pywinrm>=0.4.3,<0.6'
```

Execute uma vez:

```bash
sudo cap agent winrm-prepare Administrator@node1.exemplo.local
```

O assistente solicita a senha administrativa somente nessa execução, cria uma conta administrativa dedicada ao bootstrap, mapeia o certificado do Controller e termina com `WINRM_READY`. A senha informada e a senha aleatória da conta não são persistidas no Controller. Restrinja a porta 5986 ao endereço do Controller.

Para laboratório com certificado autossinado do listener:

```bash
sudo cap agent winrm-prepare Administrator@192.168.15.55 --insecure
```

## 3. Instalar pela Dashboard

Em **Agents → Adicionar Agent**, selecione **Windows** e **Instalar Windows via WinRM**. Informe o mesmo host preparado, Controller, região, datacenter, nome e faixa de portas. Clique em **Instalar Agent via WinRM**.

O fluxo esperado é `Aguardando Agent → Pareando → Validando → Online`. Telemetria, logs, atualização e placement usam os mesmos contratos do Agent Linux.

## 4. Diagnóstico

No Controller:

```bash
sudo cap infrastructure doctor --json
sudo cap agent winrm-prepare Administrator@HOST --json
```

No Windows, em PowerShell administrativo:

```powershell
Get-ScheduledTask -TaskName 'Capivara DSM Agent'
Get-ScheduledTaskInfo -TaskName 'Capivara DSM Agent'
Get-WinEvent -LogName Microsoft-Windows-TaskScheduler/Operational -MaxEvents 50
```

## 5. Recuperação e remoção

O pacote inclui `repair-agent.ps1`. Para reconstruir a tarefa e iniciar o runtime:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\repair-agent.ps1
```

Para remover uma instalação incompleta, preservando o registro histórico no Controller:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\repair-agent.ps1 -Uninstall
```

Depois, repita a instalação pela Dashboard. A reinstalação automática é recusada enquanto uma instalação existente for detectada, evitando sobrescrita acidental.
