# Capivara DSM 2.0.1

Release de manutenção com melhorias no fluxo de instalação remota de Agents.

## Destaques

- novo assistente `sudo cap agent ssh-prepare USER@HOST`;
- descoberta automática da conta usada pelo serviço da Dashboard;
- criação ou preservação segura da identidade SSH `id_ed25519`;
- cópia interativa da chave pública e registro da chave do host;
- instalação de regra sudoers restrita aos comandos necessários pelo bootstrap;
- validação não interativa completa com retorno `SSH_READY`;
- tutorial de instalação SSH e Central de Ajuda atualizados;
- correções no seletor de releases e nas instruções copiáveis da Dashboard.

As senhas SSH e sudo são tratadas diretamente pelos programas do sistema durante a preparação e não são armazenadas pelo Capivara.
