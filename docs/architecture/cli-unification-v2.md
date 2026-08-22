# CLI pública única — Capivara 2.x

A única CLI pública do Capivara Distributed Server Manager é `cap`.

`dsm` está descontinuado como interface pública e existe apenas como compatibilidade temporária para instalações e scripts antigos. Novos comandos, documentação, exemplos e runbooks devem usar exclusivamente `cap`.

## Roles

- Controller: operações do control plane e administração distribuída.
- Agent: operações locais do runtime e das instâncias hospedadas nessa máquina.
- Hybrid: reúne as duas superfícies.

Um Controller puro não executa runtime de jogo local. Comandos locais de lifecycle aparecem somente para Agent/Hybrid no help sensível à role.

## Migração

A implementação histórica fica isolada atrás de uma camada interna chamada pelo próprio `cap`. Isso permite retirar dependências gradualmente sem manter duas CLIs públicas concorrentes.

Enquanto a compatibilidade for necessária, o comando `dsm` pode continuar instalado para scripts e instalações antigas, mas não deve aparecer como caminho recomendado em documentação operacional nova. Quando essa camada deixar de ter consumidores, ela poderá ser removida em uma mudança de aposentadoria dedicada.

## Regra para documentação

Referências a `DSM_*`, `/opt/dsm`, nomes `dsm-*.service` e ao nome do produto Capivara DSM são identificadores técnicos e permanecem válidas. Somente exemplos e instruções de CLI para operadores devem convergir para `cap`.
