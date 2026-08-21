# CLI Unification — `cap` como comando oficial

## Status

Concluído para a linha Capivara 2.x.

## Decisão

`cap` é a única CLI pública do Capivara Distributed Server Manager.

`dsm` não é uma segunda CLI suportada para novos fluxos. Ele permanece apenas como wrapper temporário de compatibilidade para instalações, automações e scripts antigos e encaminha chamadas para `cap`.

Toda documentação nova, tutorial, runbook, exemplo de shell e automação deve usar `cap`.

## Superfície pública

A superfície pública é sensível à role local e parte de:

```text
cap help
cap help --all
```

Exemplos de grupos administrativos e operacionais:

```text
cap infrastructure ...
cap agent ...
cap customer ...
cap contract ...
cap instance ...
cap user ...
cap catalog ...
cap database ...
cap operations ...
cap config ...
cap update ...
cap server ...
cap monitor ...
cap mods ...
cap backup ...
cap runtime ...
cap steam ...
cap game ...
cap content ...
cap compatibility ...
```

Atalhos locais continuam disponíveis quando compatíveis com a role:

```text
cap start ...
cap stop ...
cap restart ...
cap status ...
```

## Roles

- Controller: control plane, administração e orquestração distribuída.
- Agent: operações locais do runtime e das instâncias hospedadas no host.
- Hybrid: reúne as duas superfícies.

Uma role incompatível é bloqueada antes do dispatch operacional. `unknown` é fail-closed.

## Compatibilidade interna

Parte da implementação histórica ainda é reutilizada por módulos internos. Essa reutilização não altera a interface pública: o operador sempre deve invocar `cap`.

O wrapper `bin/dsm` existe somente para compatibilidade de entrada e não deve aparecer em novos procedimentos operacionais. O código histórico necessário para grupos ainda não extraídos fica isolado atrás da camada interna `bin/dsm-compat`.

Fluxo conceitual durante a transição interna:

```text
usuário/script novo
      │
      ▼
     cap
      │
      ├── implementação nativa
      └── camada interna de compatibilidade, quando necessária
```

Scripts antigos que ainda chamam `dsm` entram pela camada de compatibilidade e são encaminhados ao `cap`. Isso existe para preservar compatibilidade, não para manter duas interfaces concorrentes.

## Regra para documentação e desenvolvimento

Não adicionar exemplos públicos com `dsm <comando>`.

Quando uma referência histórica ao antigo comando for necessária, ela deve ser descrita explicitamente como legado/compatibilidade e nunca apresentada como sintaxe recomendada.

Novos grupos de comando devem ser integrados ao dispatcher `cap` e respeitar a matriz de roles.

## Testes

A unificação é protegida por testes e workflows que validam:

- roteamento pelo `cap`;
- enforcement de roles;
- wrapper de compatibilidade `dsm -> cap`;
- preservação de argumentos e códigos de saída onde existe compatibilidade interna;
- Update Manager e instalação após a inversão do wrapper;
- help público centrado em `cap`.

## Política de aposentadoria

A remoção futura do wrapper `dsm` exige revisão dedicada de compatibilidade para scripts antigos, instalador e ambientes atualizados a partir de releases anteriores. Até lá, ele pode permanecer como shim, mas não recebe documentação pública nova nem funcionalidades exclusivas.
