# Tutorial — Instalar servidor DayZ para um cliente em um Agent remoto

## Objetivo

Este tutorial descreve o fluxo administrativo atual para criar um cliente, associar um contrato DayZ e provisionar uma instância em um Agent remoto usando a CLI pública oficial do Capivara.

> A CLI pública do Capivara é `cap`. O comando `dsm` existe apenas como camada temporária de compatibilidade para instalações e scripts antigos e não deve ser usado em documentação, novos scripts ou novos procedimentos operacionais.

Exemplo de topologia:

```text
Controller Capivara
192.168.15.35
        │
        ├── Cliente: CLIENTE-001
        │      └── Contrato: DayZ
        │
        └── Agent remoto
               192.168.15.45
                    │
                    └── Instância DayZ
```

Fluxo:

```text
1. Criar Customer + login
        ↓
2. Criar contrato DayZ
        ↓
3. Criar instância no Agent escolhido
        ↓
   Controller valida placement
        ↓
   Agent instala e materializa o runtime
        ↓
   Servidor pronto
```

## 1. Criar o cliente e o login

Neste exemplo:

```text
ID do cliente: CLIENTE-001
Nome: João
Usuário: joao
```

Execute no Controller ou Hybrid:

```bash
cap customer create \
  --id CLIENTE-001 \
  --name "João" \
  --username joao
```

O Capivara solicitará a senha de forma interativa:

```text
Requisitos da senha: no mínimo 8 caracteres.
Senha:
Confirme a senha:
```

A senha não deve ser fornecida na linha de comando.

O comando cria o Customer e o login associado de forma atômica, evitando a necessidade de cadastrar a entidade Customer e depois criar manualmente o usuário em uma etapa separada.

## 2. Criar um contrato DayZ para o cliente

```bash
cap contract create \
  --customer CLIENTE-001 \
  --game dayz \
  --instances 1 \
  --id CONTRACT-DAYZ-001
```

O `--id` é opcional. Quando omitido, o Capivara gera o identificador do contrato.

Resultado esperado:

```text
Contract created: CONTRACT-DAYZ-001
Customer: CLIENTE-001
Game: dayz
Instance limit: 1
```

O contrato passa a autorizar uma instância do jogo `dayz` para o Customer informado.

## 3. Selecionar o Agent remoto e criar a instância

Considere um Agent já instalado, registrado e online:

```text
Agent ID: agent-game-01
IP anunciado: 192.168.15.45
Status: active
Health: online
```

Crie a instância:

```bash
cap instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent agent-game-01 \
  --name dayz-joao-01
```

O identificador permanente do Agent é preferível ao IP. O endereço anunciado também pode ser resolvido pela CLI, mas o `agent_id` continua sendo a identidade canônica.

O Controller executa o fluxo:

```text
cap instance create
        │
        ▼
Valida Customer
        │
        ▼
Valida Contract
        │
        ▼
Resolve RuntimeDefinition do jogo
        │
        ▼
Resolve o Agent solicitado
        │
        ▼
Placement valida topologia, lifecycle, health e capabilities
        │
        ▼
Confirma inventário de portas do Agent
        │
        ▼
Reserva portas persistentemente
        │
        ▼
Cria a Instance
        │
        ▼
Enfileira provisionamento distribuído
        │
        ▼
Agent remoto
        │
        ├── materializa runtime
        ├── instala conteúdo
        ├── cria configuração
        ├── inicia a instância, quando desired-state=running
        └── reporta estado ao Controller
```

Por padrão, `cap instance create` solicita `desired-state=running`. Para criar a instância provisionada mas parada, use:

```bash
--desired-state stopped
```

Quando um jogo possui mais de um runtime elegível, informe explicitamente:

```bash
--runtime <runtime-id>
```

## Verificação

Depois da criação, acompanhe a instância pelas superfícies administrativas do Controller e pelo estado reportado pelo Agent. O retorno da criação inclui, entre outros campos:

```text
Instance ID
Agent
Runtime
Ports
Provisioning ID
Desired state
```

A criação é distribuída: o comando no Controller não instala arquivos do jogo localmente no Controller puro. O provisionamento é executado pelo Agent selecionado.

## Exclusão administrativa

A exclusão também usa a CLI `cap` e é confirmação-dirigida pelo Agent:

```bash
cap instance delete \
  --instance <instance-id> \
  --admin <usuario-admin> \
  --yes
```

O Controller marca a instância para remoção e envia o comando ao Agent proprietário. O registro persistente e as reservas de portas só são liberados depois que o Agent confirma a remoção do runtime.

A exclusão de contrato segue a mesma regra quando existem instâncias vinculadas:

```bash
cap contract delete \
  --contract CONTRACT-DAYZ-001 \
  --admin <usuario-admin> \
  --yes
```

## Resumo rápido

```bash
# 1. Criar Customer e login
cap customer create --id CLIENTE-001 --name "João" --username joao

# 2. Criar contrato DayZ
cap contract create --customer CLIENTE-001 --game dayz --instances 1 --id CONTRACT-DAYZ-001

# 3. Criar a instância no Agent remoto
cap instance create --customer CLIENTE-001 --contract CONTRACT-DAYZ-001 --game dayz --agent agent-game-01 --name dayz-joao-01
```

Topologia final:

```text
Customer CLIENTE-001
       │
       ├── Login: joao
       │
       └── CONTRACT-DAYZ-001
               │
               └── Instance
                       │
                       ▼
               agent-game-01
               192.168.15.45
                       │
                       ▼
                  DayZ runtime
```
