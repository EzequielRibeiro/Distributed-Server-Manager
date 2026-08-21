# Tutorial — Instalar servidor DayZ para um cliente em um Agent remoto

## Objetivo

Este tutorial mostra o fluxo administrativo para:

1. criar o Customer e o login do cliente;
2. criar um contrato DayZ;
3. selecionar um Agent remoto e iniciar o provisionamento da instância.

Exemplo de topologia:

```text
Controller Capivara
192.168.15.35
        │
        ├── Customer: CLIENTE-001
        │      ├── Login: joao
        │      └── Contrato: CONTRACT-DAYZ-001
        │
        └── Agent remoto
               agent-game-01
               192.168.15.45
                    │
                    └── Instância DayZ
```

## Pré-requisitos

Antes de criar a instância, o Agent remoto deve:

- estar registrado no mesmo Controller do Customer;
- estar `active` e com heartbeat `online`;
- possuir topologia válida para placement;
- anunciar suas capacidades e endereço no heartbeat;
- possuir uma faixa de portas configurada no Controller;
- reportar o inventário de sockets TCP/UDP do host;
- possuir SteamCMD e autenticação Steam válida quando exigida pelo RuntimeDefinition.

Para DayZ, o catálogo usa o runtime `dayz.stable`, provider Steam e autenticação obrigatória.

---

## 1. Criar o cliente, login e senha

O comando `dsm customer create` cria a entidade Customer e o usuário `customer` associado ao mesmo `scope` em uma única operação.

Exemplo:

```bash
dsm customer create \
  --id CLIENTE-001 \
  --name "João" \
  --username joao
```

Se houver apenas um Controller ativo, ele será selecionado automaticamente. Se existirem vários Controllers ativos, informe explicitamente:

```bash
dsm customer create \
  --id CLIENTE-001 \
  --name "João" \
  --username joao \
  --controller controller-01
```

A senha é solicitada interativamente:

```text
Requisitos da senha: no mínimo 8 caracteres.
Senha:
Confirme a senha:
```

A senha não deve ser passada na linha de comando.

Resultado esperado:

```text
Customer created: CLIENTE-001
Login: joao
Controller: controller-01
```

Vínculo criado:

```text
CLIENTE-001
    │
    └── joao
         ├── role: customer
         └── scope: CLIENTE-001
```

> O comando antigo `dsm user add joao customer CLIENTE-001` continua válido para criar somente um login quando o Customer já existe. Para um cliente novo, prefira `dsm customer create`.

---

## 2. Criar um contrato DayZ para o cliente

Crie o contrato com um ID explícito para que ele possa ser reutilizado diretamente no próximo comando:

```bash
dsm contract create \
  --id CONTRACT-DAYZ-001 \
  --customer CLIENTE-001 \
  --game dayz \
  --instances 1
```

Resultado esperado:

```text
Contract created: CONTRACT-DAYZ-001
Customer: CLIENTE-001
Game: dayz
Instance limit: 1
```

O contrato criado fica equivalente a:

```text
CONTRACT-DAYZ-001
    │
    ├── customer: CLIENTE-001
    ├── game: dayz
    ├── status: active
    └── instance_limit: 1
```

Também é possível omitir `--id`. Nesse caso, o Capivara gera um identificador único para o contrato.

Exemplo:

```bash
dsm contract create \
  --customer CLIENTE-001 \
  --game dayz \
  --instances 1
```

Use o ID retornado pelo comando na criação da instância.

---

## 3. Selecionar o Agent remoto e iniciar a instalação

Considere o Agent:

```text
Agent ID: agent-game-01
Address: 192.168.15.45
Status: active
Health: online
```

### Selecionando pelo endereço anunciado

O comando aceita o endereço anunciado pelo Agent:

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent 192.168.15.45 \
  --name dayz-joao-01
```

### Selecionando pelo Agent ID

O identificador permanente do Agent também pode ser usado e é a opção recomendada para automações:

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent agent-game-01 \
  --name dayz-joao-01
```

Quando há apenas um RuntimeDefinition registrado para o jogo, ele é selecionado automaticamente. Para DayZ, atualmente isso resolve para:

```text
dayz.stable
```

Também é possível informar explicitamente:

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --runtime dayz.stable \
  --agent 192.168.15.45 \
  --name dayz-joao-01
```

Por padrão, o estado desejado é `running`. Para apenas instalar/materializar e manter parado:

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent 192.168.15.45 \
  --name dayz-joao-01 \
  --desired-state stopped
```

---

## O que o terceiro comando faz

Informar um Agent específico **não ignora o placement**. O Agent solicitado ainda precisa passar pelas mesmas validações técnicas.

Fluxo:

```text
dsm instance create
        │
        ▼
Valida Customer
        │
        ▼
Valida Contract
        │
        ▼
Resolve Agent ID ou address
        │
        ▼
Placement / elegibilidade
        │
        ├── lifecycle
        ├── topologia
        ├── heartbeat
        ├── capabilities
        ├── recursos
        └── capacidade de portas
        │
        ▼
Consulta inventário de sockets do Agent
        │
        ├── tcp_listen
        └── udp_listen
        │
        ▼
Reserva portas no Controller
        │
        ▼
Cria Instance
        │
        ▼
Cria pedido de provisionamento B10
        │
        ▼
Agent recebe no heartbeat
        │
        ▼
Prepara workspace
        │
        ▼
Instala conteúdo via SteamCMD
        │
        ▼
Materializa runtime
        │
        ▼
Reconcile
        │
        ▼
DayZ RUNNING
```

A alocação considera simultaneamente:

```text
portas reservadas no banco
        +
portas realmente ocupadas no SO do Agent
        =
portas indisponíveis
```

O Agent Linux obtém os sockets ocupados com `ss` e envia esse inventário no heartbeat ao Controller.

---

## Retorno esperado do comando de instância

Exemplo:

```text
Instance created: <instance-id>
Agent: agent-game-01 (192.168.15.45)
Runtime: dayz.stable
Ports: {'game': 24000, 'game_aux': 24002}
Provisioning queued: <provisioning-id>
Desired state: running
```

O `instance-id` e o `provisioning-id` são gerados pelo Capivara.

O provisionamento é assíncrono do ponto de vista Controller → Agent: o pedido é persistido no Controller e entregue ao Agent autenticado pelo canal de heartbeat. O Agent executa localmente a instalação e materialização e devolve progresso/resultado ao Controller.

---

## Por que preferir o Agent ID ao IP

O endereço pode ser usado como seletor quando corresponde ao `address` anunciado pelo Agent:

```bash
--agent 192.168.15.45
```

Porém, para scripts e automações, prefira:

```bash
--agent agent-game-01
```

Se o endereço mudar:

```text
agent-game-01
    │
    ├── antes: 192.168.15.45
    └── depois: 192.168.15.60
```

a identidade permanente continua sendo:

```text
agent-game-01
```

---

## Os três comandos principais

### 1 — Criar Customer, usuário e senha

```bash
dsm customer create \
  --id CLIENTE-001 \
  --name "João" \
  --username joao
```

### 2 — Criar contrato DayZ

```bash
dsm contract create \
  --id CONTRACT-DAYZ-001 \
  --customer CLIENTE-001 \
  --game dayz \
  --instances 1
```

### 3 — Criar e instalar a instância no Agent remoto

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent 192.168.15.45 \
  --name dayz-joao-01
```

Resumo em uma sequência:

```bash
# 1. Customer + login; a senha será solicitada interativamente
dsm customer create --id CLIENTE-001 --name "João" --username joao

# 2. Contrato
dsm contract create --id CONTRACT-DAYZ-001 --customer CLIENTE-001 --game dayz --instances 1

# 3. Instância distribuída no Agent remoto
dsm instance create --customer CLIENTE-001 --contract CONTRACT-DAYZ-001 --game dayz --agent 192.168.15.45 --name dayz-joao-01
```

Topologia resultante:

```text
CLIENTE-001
    │
    ├── Login: joao
    │
    └── CONTRACT-DAYZ-001
            │
            └── Instance DayZ
                    │
                    ▼
              agent-game-01
              192.168.15.45
                    │
                    ▼
              dayz.stable
                    │
                    ▼
                 RUNNING
```

## Observação sobre autenticação Steam

O RuntimeDefinition de DayZ exige autenticação Steam. A credencial deve existir no **Agent que executará o servidor**, pois é nele que o SteamCMD executa a instalação.

Se a autenticação estiver ausente ou expirada, o provisionamento falhará de forma explícita e poderá ser repetido após a autenticação ser corrigida no Agent.
