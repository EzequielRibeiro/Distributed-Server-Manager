# Capivara DSM 2.0.10

## Agent remoto e Dashboard

- Corrige o assistente de instalação de Agent Linux para registrar e servir `agent-installation-wizard.js` corretamente.
- Corrige o roteamento de `POST /api/agents/installations/test-connection` no backend da Dashboard.
- Melhora o tratamento de respostas da API no frontend para não mascarar HTML/erros HTTP como `Unexpected token '<'`.
- Mantém o carregamento de Controller, Região e Datacenter integrado à topologia ativa.

## SSH e credenciais de deploy

- Adiciona `StrictHostKeyChecking=accept-new` ao fluxo de OpenSSH para primeiro contato seguro, preservando bloqueio quando a fingerprint já conhecida mudar.
- Melhora o diagnóstico de falhas SSH, distinguindo senha rejeitada, host key, conexão recusada, timeout e falha de `sudo`.
- Corrige `cap agent secret create` para manter diretório `0700` e secret `0600`, mas entregar ownership à conta de serviço do Capivara quando criado por root.
- Prepara o diretório `.ssh` da conta de serviço para persistência de `known_hosts`, evitando falha da Dashboard ao tentar criar esse diretório dentro de uma raiz protegida.
- Mantém a senha fora do argv e continua preferindo chave SSH quando disponível.

## Bootstrap remoto

- Corrige o bootstrap Linux para preservar a saída e o exit code reais do instalador remoto em vez de reduzir a falha a `subprocess.CalledProcessError`.
- Mantém o pairing token fora de mensagens de erro e argumentos visíveis.
- Amplia a cobertura de testes para TOFU SSH, senha rejeitada e propagação segura de erros do bootstrap.

## Instalação e infraestrutura

- Corrige o handoff da conta de serviço no fluxo HTTPS/TLS do Controller.
- Registra as páginas específicas de instalação Linux e Windows do Agent.
- Mostra dependências de deploy remoto, incluindo `sshpass`, durante a instalação e na ajuda da CLI.
- Mantém o mecanismo de Database Baseline v2 versionado e reconciliado antes do health gate.

## Documentação

- Atualiza `docs/agents/authentication/ssh-password.md` com criação segura do secret, teste direto da senha, teste via `cap agent test-connection`, uso de usuário administrativo com `sudo`, ownership da conta de serviço e comportamento de `known_hosts`.

Esta release consolida as correções necessárias para o fluxo real Controller → SSH → Agent testado em ambiente HTTPS na série 2.0.x.
