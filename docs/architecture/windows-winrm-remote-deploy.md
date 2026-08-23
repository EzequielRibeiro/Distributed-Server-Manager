# Instalação remota do Agent Windows — cronograma executado

## Dia 1 — contrato

O transporte escolhido é WinRM sobre HTTPS. Enrollment, heartbeat, telemetria, logs, update e placement continuam compartilhando os contratos distribuídos existentes.

## Dias 2 e 3 — autenticação e preparação

`cap agent winrm-prepare USER@HOST` usa uma credencial administrativa somente na sessão inicial, cria uma identidade dedicada e mapeia um certificado de cliente. A Dashboard não recebe senha. Perfis são separados por host e privados à conta do serviço.

## Dias 4 e 5 — bootstrap e Dashboard

A API aceita `method=winrm` somente com `platform=windows`, executa preflight, recusa sobrescrever Agent existente e inicia o instalador oficial da release com token de uso único. A interface seleciona automaticamente Windows, mostra somente os campos WinRM e acompanha o Agent até `Online`.

## Dias 6 e 7 — operação e recuperação

O runtime Windows já publica a mesma telemetria e logs do Agent Linux. `repair-agent.ps1` reconstrói a Scheduled Task ou remove uma instalação incompleta. Falha de bootstrap expira imediatamente o token ainda não consumido.

## Dias 8 e 9 — segurança, testes e ajuda

Validações cobrem host, porta, perfil, preflight, detecção de instalação e confirmação do bootstrap. O pacote Windows passa a incluir o utilitário de recuperação. O tutorial está disponível no GitHub e na busca da Ajuda da Dashboard.

## Dia 10 — critérios de liberação

- WinRM HTTPS acessível somente pelo Controller;
- certificado do listener validado em produção;
- `WINRM_READY` confirmado antes do uso da Dashboard;
- pacote e checksum Windows presentes na release;
- fluxo alcança heartbeat `online`;
- testes WinRM, Dashboard, pacote Windows e Central de Ajuda aprovados.

Publicação e criação de release permanecem ações separadas e exigem autorização explícita.
