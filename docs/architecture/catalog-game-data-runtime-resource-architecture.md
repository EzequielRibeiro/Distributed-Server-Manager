# Catálogo, Game Data, Runtime e Perfis de Recursos

## Objetivo

Separar definitivamente quatro domínios que antes apareciam misturados na interface: definição do jogo, arquivos compartilhados de game-data, parâmetros/perfis técnicos de execução e instâncias pertencentes aos contratos dos clientes.

## Regra de domínio

O Catálogo é uma ferramenta administrativa. Ele não cria instâncias de clientes. A criação de instâncias ocorre no contexto Cliente → Contrato.

O Catálogo administra:

- definições de jogos e runtimes;
- disponibilidade de game-data nos Agents;
- instalação, atualização e verificação de game-data;
- parâmetros de processo/startup;
- templates de configuração;
- perfis de recursos;
- conteúdo adicional compatível;
- versões e integridade.

## Entidades

### Game Catalog Definition

Descreve jogo, edição, variante, provider, versão, requisitos, processo e rede. O `RuntimeDefinition` v2 existente continua sendo a fonte principal para provider, executable, argumentos, requisitos e diretório de instalação.

### Game Data

É a base compartilhada instalada no Agent, por exemplo `/opt/dsm/game-data/minecraft/vanilla`. Não pertence a um cliente e não deve ser confundida com a árvore de arquivos de uma instância.

Operações administrativas previstas: instalar, atualizar, verificar, reparar, remover, listar arquivos, ler, editar, criar, renomear, enviar e excluir. Escritas devem ser confinadas ao diretório de game-data autorizado, auditadas e marcar o conteúdo como modificado quando divergirem da base verificada.

### Runtime / Resource Profile

O runtime define como o jogo executa. O perfil de recursos define quanto uma instância daquele jogo pode consumir. Perfis possuem identificadores estáveis e limites em unidades explícitas (`memory_mb`, `storage_mb`, CPU e limites opcionais).

Exemplo: Minecraft `standard` = 8192 MB RAM / 25600 MB armazenamento; `large` = 16384 MB RAM / 30720 MB armazenamento.

### Instance

É a materialização concreta pertencente a um contrato. A instância referencia runtime e perfil permitidos, recebe portas, configuração e filesystem próprios. Ela nunca altera silenciosamente a base compartilhada de game-data.

## Fluxo de criação pelo contrato

```text
Cliente → Contrato → Criar Instância
                    ↓
                 Placement
                    ↓
               Agent elegível
                    ↓
            game-data disponível?
              ├─ sim → reutilizar
              └─ não → instalar sob demanda
                    ↓
             materializar instância
                    ↓
       aplicar recursos + portas + config
                    ↓
                 startup
```

O contrato determina quais jogos e perfis de recursos o cliente pode selecionar. O Placement deve considerar capacidade livre suficiente para o perfil solicitado.

## Parâmetros de execução

A administração de parâmetros pertence ao detalhe do jogo no Catálogo, não à tela de uma instância. A definição deve evoluir o `process` do RuntimeDefinition para representar de forma validável: executable, argumentos/comando, diretório de trabalho, variáveis, ambiente, arquivo principal, shutdown, timeout e regras de entrada. Valores dinâmicos de instância são resolvidos apenas na materialização.

## Configuração

O `ConfigurationProfile` existente já modela arquivos conhecidos e editáveis. Ele deve continuar representando quais arquivos podem ser gerados/editados, enquanto templates e valores default são aplicados à instância sem converter game-data em configuração privada do cliente.

## Segurança do gerenciador de arquivos de game-data

O futuro endpoint de escrita deve exigir função administrativa, resolver caminhos com `Path.resolve()`, rejeitar `..`, symlinks que escapem da raiz, arquivos protegidos e payloads acima dos limites definidos. Cada mutação deve produzir evento/auditoria contendo Agent, runtime, caminho, usuário, operação e estado de integridade resultante.

## Componentes existentes reutilizados

- Catalog v2 e `RuntimeDefinition`;
- `ConfigurationProfile`;
- `agent_game_data_api.py` e `agent_game_data_http.py` para fila/status de instalação de game-data;
- provider/resolver do instalador;
- Agent Game Data Repository e jobs distribuídos;
- placement e inventário/capabilities dos Agents;
- Universal Configuration, Content, Events e Observability;
- RBAC do Controller;
- infraestrutura Dashboard v3.

## Limites desta fundação

Esta mudança estabelece o modelo, os perfis de recursos e a nova experiência administrativa do Catálogo. O gerenciador remoto de arquivos com mutação e a aplicação coercitiva dos perfis pelo runtime devem ser implementados nas etapas específicas do roadmap, com testes de segurança e E2E antes de ativação em produção.
