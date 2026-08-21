# Tutorial — Instalar servidor DayZ para um cliente em um Agent remoto

## Objetivo

Este tutorial descreve o fluxo administrativo desejado para criar um cliente, associar um contrato DayZ e provisionar uma instância em um Agent remoto.

Exemplo de topologia:

```text
Controller Capivara
192.168.15.35
        │
        ├── Cliente: joao
        │      └── Contrato: DayZ
        │
        └── Agent remoto
               192.168.15.45
                    │
                    └── Instância DayZ
```

Fluxo:

```text
1. Criar cliente/login
        ↓
2. Criar contrato DayZ
        ↓
3. Criar instância no Agent escolhido
        ↓
   Agent instala DayZ
        ↓
   Servidor pronto
```

> **Nota sobre o estado atual da CLI:** o comando de criação de usuário já existe. Os comandos `dsm contract create` e `dsm instance create` abaixo representam a interface administrativa planejada; o modelo correspondente já existe no backend, mas esses dispatchers ainda precisam ser expostos pela CLI pública.

---

## 1. Criar o usuário do cliente

Neste exemplo:

```text
ID do cliente: CLIENTE-001
Usuário: joao
```

O Customer `CLIENTE-001` deve existir previamente no Controller. O login é criado com:

```bash
dsm user add joao customer CLIENTE-001
```

O Capivara solicitará a senha de forma interativa:

```text
Requisitos da senha: no mínimo 8 caracteres.
Senha:
Confirme a senha:
```

A senha não deve ser informada diretamente na linha de comando.

O vínculo criado é:

```text
joao
  │
  ├── role: customer
  └── scope: CLIENTE-001
```

Usuários com papel `customer` precisam obrigatoriamente possuir um `scope`, que corresponde ao Customer ao qual o login pertence.

> Criar o login e cadastrar a entidade Customer são operações diferentes.

---

## 2. Criar um contrato DayZ para o cliente

Interface administrativa planejada:

```bash
dsm contract create \
  --customer CLIENTE-001 \
  --game dayz \
  --instances 1
```

Resultado esperado:

```text
Contrato criado com sucesso

ID: CONTRACT-DAYZ-001
Cliente: CLIENTE-001
Jogo: DayZ
Limite de instâncias: 1
Status: active
```

Relação criada:

```text
CLIENTE-001
      │
      └── CONTRACT-DAYZ-001
                │
                ├── game: dayz
                ├── status: active
                └── instance_limit: 1
```

O Capivara já possui no backend o conceito de `service_contracts`, incluindo Customer, jogo, estado do contrato e limite de instâncias.

### Estado atual

A CLI pública atual ainda não possui o dispatcher:

```bash
dsm contract create
```

Portanto, este comando deve ser considerado a sintaxe administrativa a ser implementada, e não um comando já disponível em produção.

---

## 3. Selecionar o Agent remoto e instalar o servidor DayZ

Considere um Agent Capivara instalado e registrado em outra máquina:

```text
Agent ID: agent-game-01
IP: 192.168.15.45
Status: online
```

A interface administrativa planejada para criar a instância é:

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent agent-game-01 \
  --name dayz-joao-01
```

O cadastro do Agent associa:

```text
agent-game-01 → 192.168.15.45
```

O Controller deverá executar o fluxo:

```text
dsm instance create
        │
        ▼
Valida CLIENTE-001
        │
        ▼
Valida CONTRACT-DAYZ-001
        │
        ▼
Confirma autorização para DayZ
        │
        ▼
Localiza agent-game-01
        │
        ▼
Verifica Agent online
        │
        ▼
Verifica recursos/capabilities
        │
        ▼
Reserva portas
        │
        ▼
Cria Instance
        │
        ▼
Envia provisionamento ao Agent
        │
        ▼
Agent 192.168.15.45
        │
        ├── prepara diretórios
        ├── materializa runtime
        ├── instala conteúdo DayZ
        ├── gera configuração
        ├── reserva recursos
        └── inicia servidor
        │
        ▼
DayZ RUNNING
```

Retorno esperado:

```text
Instância criada

Instance ID: dayz-joao-01
Customer: CLIENTE-001
Contract: CONTRACT-DAYZ-001
Game: dayz
Agent: agent-game-01
Address: 192.168.15.45
Status: provisioning
```

Exemplo de progresso:

```text
[10%] Placement validado
[20%] Agent selecionado
[30%] Portas reservadas
[40%] Runtime materializado
[55%] Instalando DayZ
[75%] Configurando servidor
[90%] Iniciando runtime
[100%] Servidor disponível
```

---

## Por que selecionar pelo ID do Agent e não pelo IP

Embora seja possível imaginar uma interface como:

```bash
--agent 192.168.15.45
```

o modelo preferencial deve usar o identificador permanente do Agent:

```bash
--agent agent-game-01
```

O cadastro contém o endereço atual:

```text
Agent ID: agent-game-01
Hostname: servidor-jogos-01
IP: 192.168.15.45
Status: online
```

Se o endereço mudar posteriormente:

```text
192.168.15.45
      ↓
192.168.15.60
```

a instância permanece vinculada ao mesmo Agent:

```text
agent-game-01
```

Isso evita vincular permanentemente a instância a um endereço de rede que pode mudar.

---

## Os três comandos do tutorial

### 1 — Criar login do cliente

```bash
dsm user add joao customer CLIENTE-001
```

O Capivara solicita:

```text
Senha:
Confirme a senha:
```

### 2 — Criar contrato DayZ

```bash
dsm contract create \
  --customer CLIENTE-001 \
  --game dayz \
  --instances 1
```

Exemplo de contrato retornado:

```text
CONTRACT-DAYZ-001
```

### 3 — Criar e instalar a instância no Agent remoto

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent agent-game-01 \
  --name dayz-joao-01
```

Topologia final:

```text
Cliente
  CLIENTE-001
       │
       ├── Login: joao
       │
       └── Contrato DayZ
               │
               └── dayz-joao-01
                       │
                       ▼
               agent-game-01
               192.168.15.45
                       │
                       ▼
                  DayZ Server
                    RUNNING
```

---

## Resumo rápido

```bash
# 1. Criar login do cliente
dsm user add joao customer CLIENTE-001

# 2. Criar contrato DayZ — interface planejada
dsm contract create --customer CLIENTE-001 --game dayz --instances 1

# 3. Criar a instância no Agent remoto — interface planejada
dsm instance create --customer CLIENTE-001 --contract CONTRACT-DAYZ-001 --game dayz --agent agent-game-01 --name dayz-joao-01
```

## Lacunas atuais da CLI

Já existe atualmente:

```bash
dsm user add <usuario> customer <scope>
```

Também existem os conceitos de Customer, Contract, Agent, Instance, jogo, runtime distribuído e gerenciamento de portas.

Ainda precisam ser expostos de forma completa como comandos administrativos públicos:

```bash
dsm customer ...
dsm contract ...
dsm instance create ...
```

A experiência administrativa final pretendida é:

```text
dsm customer create
        ↓
dsm user add
        ↓
dsm contract create
        ↓
dsm instance create --agent ...
        ↓
Servidor instalado no Agent selecionado
```
