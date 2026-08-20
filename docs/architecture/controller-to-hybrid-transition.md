# Controller → Hybrid: transição segura de papel de infraestrutura

## Objetivo

Permitir que um Node já instalado como `controller` passe a operar como `hybrid` sem reinstalar o Capivara e sem recriar ou substituir a identidade persistida do Controller.

A transição adiciona o papel Agent ao mesmo host e preserva o estado administrativo existente.

## Invariantes

A promoção deve preservar:

- `nodes.id` existente;
- `controllers.id` existente;
- Customers;
- Contracts;
- Instances;
- ownership e vínculos já persistidos;
- arquivos e configurações não relacionados ao papel Agent.

A transição não deve criar um segundo Controller nem um segundo Agent para o mesmo Node.

## Estados suportados

Nesta fase somente a transição abaixo é suportada:

```text
controller -> hybrid
```

Uma execução posterior sobre um Node já `hybrid` deve ser idempotente.

A transição inversa `hybrid -> controller` não faz parte desta fase. Quando implementada, deverá bloquear a remoção do papel Agent enquanto houver instâncias ou outras dependências hospedadas no Agent local.

## Fluxo

```text
Node controller existente
        |
        v
validar Node + Controller
        |
        v
transação de identidade/topologia
        |
        +-- preservar Node
        +-- preservar Controller
        +-- role = hybrid
        +-- criar Agent local, se ausente
        +-- criar topologia local mínima, se ausente
        +-- manter pools de portas do contrato vigente
        |
        v
reconciliação local idempotente
        |
        +-- agent.conf
        +-- capabilities reais
        +-- sockets observados via ss
        +-- runtime inventory
        +-- heartbeat
        |
        v
Agent local online
        |
        v
placement avalia requisitos reais
```

## Atomicidade e recuperação

A alteração de identidade/topologia no banco é transacional.

A reconciliação do host ocorre depois da confirmação dessa transação porque envolve filesystem e coleta de estado do sistema operacional. Se a reconciliação local falhar, a identidade persistida não é revertida artificialmente. A mesma operação pode ser executada novamente com segurança.

Esse desenho evita rollback parcial entre banco e filesystem e fornece recuperação idempotente.

## Agent local

O Agent criado para o modo híbrido pertence ao mesmo Node e ao mesmo Controller já existentes.

Exemplo:

```text
horizon-server
├── Controller: controller-horizon-server
└── Agent:      agent-horizon-server
```

O Agent local recebe inventory e heartbeat factual, não um readiness presumido.

## Readiness e placement

A promoção de papel não equivale, sozinha, a afirmar que qualquer jogo pode ser instalado.

O placement continua avaliando:

- Controller ativo;
- Agent ativo;
- localização ativa;
- Datacenter ativo;
- Region ativa;
- Agent online;
- capabilities exigidas pelo runtime;
- CPU, RAM e storage quando exigidos;
- faixa de portas e disponibilidade efetiva;
- sockets reais observados no host.

Para DayZ, por exemplo, o Agent híbrido só será elegível quando possuir os requisitos definidos no catálogo, incluindo `native-linux`, `steamcmd` e bloco UDP disponível.

## SteamCMD no modo híbrido

A coleta de capabilities reconhece tanto instalações disponíveis no `PATH` quanto o SteamCMD gerenciado pelo Capivara em:

```text
${DSM_ROOT}/tools/steamcmd/steamcmd.sh
```

## Portas

O Agent local usa a política de portas já existente do projeto. A migration 011 mantém pools padrão administráveis para novos Agents:

```text
TCP 24000-24999
UDP 24000-24999
```

A disponibilidade efetiva continua considerando reservas em `instance_ports` e sockets reais reportados pelo host.

## CLI

Consulta:

```text
cap infrastructure role show
```

Promoção:

```text
cap infrastructure role set hybrid
```

A CLI também suporta parâmetros explícitos de identidade para diagnóstico/administração e `--identity-only` para cenários controlados de recuperação.

## Dashboard

A área `Infraestrutura · Agents` mostra o estado do Node local e, quando aplicável, oferece a promoção para Hybrid.

A ação de mudança de papel:

- é restrita a `admin`;
- exige confirmação explícita;
- usa a mesma camada de domínio da CLI;
- atualiza o estado exibido depois da operação.

Contas com papel `controller` continuam podendo administrar Agents, mas não podem alterar o papel estrutural do Node.

## API

```text
GET  /api/infrastructure/role
POST /api/infrastructure/role
```

O POST aceita somente a transição suportada nesta fase e aplica as mesmas validações de segurança da camada de domínio.

## Testes obrigatórios

A cobertura da transição inclui:

- Controller existente antes da promoção;
- preservação de Node e Controller;
- criação de exatamente um Agent local;
- idempotência;
- rejeição de conflitos de identidade;
- preservação de Customers e Contracts;
- reconciliação de `agent.conf` sem sobrescrever segredos;
- runtime inventory e heartbeat;
- capabilities e sockets reais;
- regressão Controller -> Hybrid -> placement DayZ;
- autorização da API;
- contrato da interface da Dashboard.

## Regra operacional

A transição deve ser tratada como operação explícita de lifecycle de infraestrutura, e não como efeito colateral de `install.sh --reinstall` ou de uma atualização de release.

Atualizar arquivos do Capivara e alterar o papel persistido de um Node são operações diferentes e devem permanecer separadas.
