# Administração de clientes, contratos e instâncias pela CLI

Este documento é a referência operacional para o fluxo administrativo de Customer no Capivara DSM.

> A CLI pública oficial é `cap`. O comando `dsm` existe apenas como compatibilidade temporária e não deve ser usado em novos procedimentos.

## Visão geral

O fluxo normal no Controller ou Hybrid é:

```text
Customer + login
      ↓
Contrato de serviço
      ↓
Instância
      ↓
Placement
      ↓
Agent
      ↓
Runtime do jogo
```

## 1. Criar um Customer e seu primeiro login

Use `cap customer create` para um cliente novo:

```bash
sudo cap customer create \
  --id CLIENTE-001 \
  --name "Cliente Exemplo" \
  --username cliente01
```

A senha é solicitada de forma interativa e não deve ser passada na linha de comando.

O login criado usa:

```text
role: customer
scope_id: CLIENTE-001
```

O `scope_id` identifica o Customer ao qual o login pertence.

### `cap customer create` versus `cap user add`

Para criar um Customer novo, prefira sempre:

```bash
cap customer create --id ID --name NOME --username LOGIN
```

`cap user add` não cria a entidade Customer. Para um login `customer`, o scope é obrigatório:

```bash
sudo cap user add segundo-login customer CLIENTE-001
```

Esse formato só deve ser usado quando o Customer já existe e o objetivo é associar um login ao mesmo scope.

> A área moderna do cliente também usa `customer_account_members` para definir a função da conta (`owner`, `manager` ou `member`). O primeiro login operacional de um Customer deve ter membership `owner`. Instalações antigas ou bases criadas antes da correção desse fluxo podem precisar de reconciliação de membership antes do acesso à área do cliente.

## 2. Criar contrato

Exemplo:

```bash
sudo cap contract create \
  --customer CLIENTE-001 \
  --game dayz \
  --instances 1 \
  --id CONTRACT-DAYZ-001
```

`--id` é opcional. Quando omitido, o Capivara gera o identificador do contrato.

O contrato determina, entre outros dados:

- Customer proprietário;
- jogo autorizado;
- estado do contrato;
- limite de instâncias;
- validade, quando configurada.

## 3. Criar uma instância

O Agent precisa estar registrado, ativo e elegível para placement.

```bash
sudo cap instance create \
  --customer CLIENTE-001 \
  --contract CONTRACT-DAYZ-001 \
  --game dayz \
  --agent agent-game-01 \
  --name dayz-cliente01
```

O `agent_id` é a identidade canônica do Agent e deve ser preferido ao endereço IP quando conhecido.

O Controller valida Customer, contrato, runtime, placement, Agent, capacidades e portas antes de enfileirar o provisionamento distribuído.

Por padrão, a instância é criada com estado desejado `running`. Para provisionar parada:

```bash
--desired-state stopped
```

Quando o jogo possui mais de um runtime elegível:

```bash
--runtime <runtime-id>
```

## 4. Usuários e senha

Listar usuários:

```bash
sudo cap user list
```

Alterar senha:

```bash
sudo cap user passwd <usuario>
```

Remover usuário:

```bash
sudo cap user remove <usuario>
```

Roles administrativas e de cliente são diferentes. Um usuário `customer` deve possuir `scope_id` válido e não deve receber acesso à área administrativa.

## 5. Login web

Existem duas superfícies de login separadas:

```text
/login.html           administração
/customer-login.html  cliente
```

Após autenticação, a role define a área de destino:

```text
customer                    → /customer.html
admin/controller/operator   → /index.html
```

A área do cliente inclui:

```text
/customer.html
/customer-members.html
/customer-instance.html
```

Rotas administrativas não devem ser abertas por usuários `customer`.

## 6. Membership e permissões

Há três conceitos distintos:

```text
dashboard_users
  identidade de login e role global

customer_account_members
  vínculo do login com o Customer e função da conta
  owner | manager | member

instance_access
  permissão específica por instância
  viewer | operator | manager
```

`owner` é função da conta do Customer. `viewer`, `operator` e `manager` em `instance_access` são perfis por instância e não substituem o membership da conta.

## 7. Exclusão administrativa

Excluir instância:

```bash
sudo cap instance delete \
  --instance <instance-id> \
  --admin <usuario-admin> \
  --yes
```

Excluir contrato:

```bash
sudo cap contract delete \
  --contract <contract-id> \
  --admin <usuario-admin> \
  --yes
```

Quando há runtime distribuído, a remoção da instância é confirmação-dirigida pelo Agent. Reservas persistentes só devem ser liberadas depois da confirmação de remoção.

## 8. Catálogo da área do cliente

O catálogo lateral pode apresentar jogos contratados e jogos conhecidos pelo catálogo global.

Com contrato ativo, o item pode abrir a criação ou a instância existente. Sem contrato ativo, o cliente permanece dentro da área do cliente e recebe uma orientação de contratação. O frontend não deve navegar para páginas administrativas como `/contract-demo.html`.

## 9. Diagnóstico rápido

Confirme o usuário:

```bash
sudo cap user list
```

Confirme a role e o scope esperados:

```text
cliente01  customer  CLIENTE-001  active
```

Se o login web autenticar mas `/api/customer/auth/me` rejeitar o acesso, verifique se o usuário também possui membership em `customer_account_members` para o mesmo Customer.

## Resumo

```bash
# Customer + login
sudo cap customer create --id CLIENTE-001 --name "Cliente Exemplo" --username cliente01

# Contrato
sudo cap contract create --customer CLIENTE-001 --game dayz --instances 1 --id CONTRACT-DAYZ-001

# Instância
sudo cap instance create --customer CLIENTE-001 --contract CONTRACT-DAYZ-001 --game dayz --agent agent-game-01 --name dayz-cliente01
```
