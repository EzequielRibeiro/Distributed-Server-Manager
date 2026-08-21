# Tutorial — Instalar e remover servidor DayZ em um Agent remoto

## Objetivo

Este tutorial mostra o fluxo administrativo para:

1. criar o Customer e o login do cliente;
2. criar um contrato DayZ;
3. selecionar um Agent remoto e iniciar o provisionamento da instância;
4. excluir uma instância como administrador;
5. excluir um contrato como administrador, removendo automaticamente todas as instâncias vinculadas.

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

```bash
dsm customer create \
  --id CLIENTE-001 \
  --name "João" \
  --username joao
```

Se houver vários Controllers ativos:

```bash
dsm customer create \
  --id CLIENTE-001 \
  --name "João" \
  --username joao \
  --controller controller-01
```

A senha é solicitada interativamente e não deve ser passada na linha de comando.

Resultado esperado:

```text
Customer created: CLIENTE-001
Login: joao
Controller: controller-01
```

---

## 2. Criar um contrato DayZ para o cliente

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

O parâmetro `--id` pode ser omitido; nesse caso o Capivara gera um identificador único.

---

## 3. Selecionar o Agent remoto e iniciar a instalação

Selecionando pelo endereço anunciado:

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent 192.168.15.45 \
  --name dayz-joao-01
```

Selecionando pelo Agent ID, recomendado para automações:

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent agent-game-01 \
  --name dayz-joao-01
```

O Agent explicitamente escolhido ainda passa por lifecycle, topologia, heartbeat, capabilities, recursos e capacidade de portas. O Controller também considera as portas realmente ocupadas no SO do Agent, informadas pelo inventário `ss` no heartbeat.

Por padrão o estado desejado é `running`. Para provisionar parado:

```bash
dsm instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent 192.168.15.45 \
  --name dayz-joao-01 \
  --desired-state stopped
```

Fluxo resumido:

```text
Customer / Contract
        ↓
Agent selecionado
        ↓
Placement e elegibilidade
        ↓
Reserva de portas
        ↓
Instance persistida
        ↓
Fila de provisionamento
        ↓
Heartbeat autenticado
        ↓
Agent instala conteúdo
        ↓
Materializa runtime
        ↓
Reconcile
        ↓
RUNNING
```

---

## 4. Excluir uma instância — somente nível Admin

A exclusão de uma instância é uma operação destrutiva e exige um usuário do Dashboard com role `admin` ativo.

Exemplo:

```bash
dsm instance delete \
  --instance cliente-001-dayz-001 \
  --admin administrador \
  --yes
```

O Capivara solicitará a senha do administrador de forma interativa:

```text
Senha do admin administrador:
```

A senha administrativa não é aceita como argumento de linha de comando.

O comando não apaga imediatamente a instância do banco. O fluxo é:

```text
dsm instance delete
        ↓
Valida --yes
        ↓
Autentica usuário role=admin
        ↓
Marca Instance = deleting
        ↓
Enfileira action=remove
        ↓
Agent recebe no heartbeat
        ↓
Agent para o runtime, se necessário
        ↓
Agent remove a materialização da instância
        ↓
Agent confirma completed
        ↓
Controller exclui Instance
        ↓
Libera reservas de portas e relações operacionais
```

Isso evita que o Controller esqueça uma instância que ainda esteja rodando no Agent remoto.

O conteúdo compartilhado do jogo permanece preservado no Agent; a exclusão remove a materialização e o cadastro daquela instância, não a instalação compartilhada do jogo utilizada por outras instâncias.

Resultado inicial esperado:

```text
Instance deletion started: cliente-001-dayz-001
Agent: agent-game-01
Removal command: <command-id>
The database record and port reservations are released after Agent confirmation.
```

---

## 5. Excluir um contrato — somente nível Admin

Excluir um contrato também é uma operação exclusiva de `admin`.

```bash
dsm contract delete \
  --contract CONTRACT-DAYZ-001 \
  --admin administrador \
  --yes
```

A senha do administrador será solicitada interativamente.

### Regra de cascata

Ao excluir o contrato, **todas as instâncias vinculadas ao contrato são obrigatoriamente excluídas**.

Exemplo:

```text
CONTRACT-DAYZ-001
        │
        ├── dayz-001
        ├── dayz-002
        └── dayz-003
```

Executando:

```bash
dsm contract delete \
  --contract CONTRACT-DAYZ-001 \
  --admin administrador \
  --yes
```

O fluxo será:

```text
Contrato
   │
   ▼
status = deleting
   │
   ├── Instance 1 → deleting → Agent remove → confirmação
   ├── Instance 2 → deleting → Agent remove → confirmação
   └── Instance 3 → deleting → Agent remove → confirmação
                           │
                           ▼
              nenhuma Instance restante
                           │
                           ▼
                   contrato excluído
```

O contrato só é fisicamente removido do banco depois que todas as instâncias vinculadas forem confirmadas como removidas pelos respectivos Agents.

Se o contrato não possuir nenhuma instância, ele é excluído imediatamente.

Se uma instância estiver vinculada a um Agent cuja lifecycle administrativa não esteja `active`, o Capivara recusa iniciar a exclusão em cascata, evitando remoção parcial silenciosa.

---

## Hierarquia de permissões

Os comandos de criação pertencem ao plano administrativo normal do Controller:

```text
dsm customer create
dsm contract create
dsm instance create
```

Os comandos destrutivos estão em uma camada hierárquica superior:

```text
ADMIN
  │
  ├── dsm instance delete
  └── dsm contract delete
```

Eles exigem simultaneamente:

```text
execução no Controller / ambiente administrativo
        +
usuário Dashboard ativo
        +
role = admin
        +
senha administrativa válida
        +
--yes
```

Um usuário `customer`, `operator` ou `controller` do Dashboard não pode autorizar essas exclusões.

---

## Sequência principal do tutorial

```bash
# 1. Criar Customer + login
dsm customer create --id CLIENTE-001 --name "João" --username joao

# 2. Criar contrato DayZ
dsm contract create --id CONTRACT-DAYZ-001 --customer CLIENTE-001 --game dayz --instances 1

# 3. Criar instância no Agent remoto
dsm instance create --customer CLIENTE-001 --contract CONTRACT-DAYZ-001 --game dayz --agent 192.168.15.45 --name dayz-joao-01

# 4. Excluir somente uma instância — Admin
dsm instance delete --instance cliente-001-dayz-001 --admin administrador --yes

# 5. Excluir o contrato e todas as suas instâncias — Admin
dsm contract delete --contract CONTRACT-DAYZ-001 --admin administrador --yes
```

## Observação sobre autenticação Steam

O RuntimeDefinition de DayZ exige autenticação Steam. A credencial deve existir no Agent que executará o servidor, pois é nele que o SteamCMD executa a instalação.

Se a autenticação estiver ausente ou expirada, o provisionamento falhará de forma explícita e poderá ser repetido após a autenticação ser corrigida no Agent.
