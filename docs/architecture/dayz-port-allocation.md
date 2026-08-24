# DayZ Port Allocation Policy

## Status

Architecture Decision — Active

## Context

O Capivara DSM suporta múltiplas instâncias de servidores DayZ
executadas simultaneamente no mesmo Node.

Os testes realizados durante o desenvolvimento demonstraram que uma
instância DayZ não utiliza apenas a porta especificada através do
parâmetro:

    -port=P

Por exemplo, uma instância iniciada com:

    -port=24000

abriu os seguintes sockets UDP:

    24000
    24002

Uma segunda instância iniciada com:

    -port=24100

abriu:

    24100
    24102

O perfil também configura uma porta Steam Query independente, usada
para publicar a instância no navegador de servidores.


## Problem

Tratar somente a porta principal do servidor como recurso reservado
pode provocar colisões entre instâncias.

Por exemplo:

    Instance A
        game = 24000
        auxiliary = 24002

Se outra instância receber:

    game = 24002

a segunda instância tentará utilizar uma porta que já pertence à
primeira.

Portanto, uma porta DayZ não pode ser alocada isoladamente.


## Decision

O Capivara DSM administrará portas DayZ através de blocos de portas
por instância.

A porta principal do bloco será chamada:

    game

A porta UDP observada em P + 2 será chamada:

    game_aux

A porta configurável de consulta e publicação Steam será chamada:

    steam_query

A política inicial utilizará espaçamento de 10 portas entre as bases
dos blocos.


## Initial allocation model

Exemplo:

    Instance A

        game      UDP 24000
        game_aux  UDP 24002
        steam_query UDP 24003

    Instance B

        game      UDP 24010
        game_aux  UDP 24012
        steam_query UDP 24013

    Instance C

        game      UDP 24020
        game_aux  UDP 24022
        steam_query UDP 24023

    Instance D

        game      UDP 24030
        game_aux  UDP 24032
        steam_query UDP 24033


## Block size

A base de cada bloco avança em intervalos de:

    10

Portanto:

    BASE(n + 1) = BASE(n) + 10

O espaço não utilizado dentro do bloco permanece reservado
conceitualmente para expansão futura da política DayZ.

Exemplo:

    24000-24009  -> Instance A
    24010-24019  -> Instance B
    24020-24029  -> Instance C


## Allocation range

A faixa inicial administrada pelo Capivara para DayZ será:

    24000-24999/UDP

Com blocos de 10 portas, essa faixa permite até 100 blocos lógicos
antes de qualquer futura expansão ou alteração da política.


## Allocation rules

O alocador DayZ deve obedecer às seguintes regras:

1. Uma instância recebe um bloco lógico de portas.

2. A porta `game` corresponde à base do bloco.

3. A porta `game_aux` corresponde a:

       game + 2

4. A porta `steam_query` corresponde a:

       game + 3

5. As bases válidas seguem o intervalo configurado de blocos:

       24000
       24010
       24020
       ...

6. O alocador deve verificar reservas existentes no banco
   `instance_ports`.

7. O alocador também deve verificar sockets realmente ocupados no
   sistema operacional.

8. Um bloco somente pode ser atribuído quando todas as portas
   obrigatórias estiverem disponíveis.

9. A reserva deve ser atômica.

   Ou todas as portas necessárias são reservadas ou nenhuma alteração
   permanece no banco.

10. Uma operação Stop não libera as portas da instância.

11. Uma operação Restart não altera as portas da instância.

12. A instância deve reutilizar o mesmo bloco após novos Starts.

13. A liberação do bloco ocorre quando a instância é removida ou por
    uma operação administrativa explícita de realocação.

14. A unicidade das portas é considerada dentro do Node.

15. O alocador nunca deve confiar somente no banco de dados para
    determinar se uma porta está disponível.

16. Falha ao consultar o estado real das portas do sistema operacional
    deve interromper a alocação em vez de assumir que a porta está
    livre.


## Persistence

As portas pertencentes à instância são armazenadas na tabela:

    instance_ports

Exemplo:

    instance_id
    node_id
    name
    protocol
    port
    bind_address

Para DayZ, inicialmente serão persistidas:

    game
    game_aux
    steam_query


## Runtime configuration

Após a alocação, `game` deve ser aplicado ao processo e `steam_query`
deve ser gravado em `serverDZ.cfg`. A porta `game_aux` é derivada pelo
processo a partir da porta principal, mas continua reservada e monitorada.

Exemplo:

    ARGS="-port=24000 -config=serverDZ.cfg"
    steamQueryPort = 24003;

O usuário não deve precisar escolher manualmente a porta durante o
provisionamento normal.


## Runtime reconciliation

O estado persistido pelo Capivara deve refletir o processo realmente
observado no Node.

A existência de uma reserva de porta não significa que a instância
esteja online.

Da mesma forma:

    reserved port != active socket

A reserva pertence à configuração persistente da instância.

O socket pertence ao estado de execução.


## Experimental evidence

Durante os testes de desenvolvimento foram executadas
simultaneamente duas instâncias DayZ.

Instance cli-demo-001-dayz-005:

    -port=24000

Sockets observados:

    UDP 24000
    UDP 24002

Instance cli-demo-001-dayz-004:

    -port=24100

Sockets observados:

    UDP 24100
    UDP 24102

As duas instâncias permaneceram simultaneamente operacionais.


## Allocator prototype

O protótipo `allocate_dayz_ports()` foi testado consultando
simultaneamente:

- reservas existentes em `instance_ports`;
- sockets UDP reais através do comando `ss`.

No teste da Etapa 192 estavam ocupados:

    24000
    24002
    24100
    24102

O protótipo encontrou:

    game     = 24001
    game_aux = 24003

Esse resultado confirmou que a detecção de colisões estava
funcionando.

Entretanto, também demonstrou que permitir qualquer número como porta
base produziria uma distribuição pouco previsível.

Por esse motivo foi adotada a política formal de blocos descrita neste
documento.


## Required allocator behavior

Após a adoção desta política, diante do cenário:

    24000/24002 ocupados
    24100/24102 ocupados

o alocador não deve retornar:

    24001/24003

Ele deve procurar somente bases válidas de blocos:

    24000
    24010
    24020
    24030
    ...

Assim, nesse cenário, a primeira base disponível esperada será:

    24010

desde que nenhuma porta obrigatória desse bloco esteja ocupada ou
reservada.


## Future work

Novas portas somente poderão ser incorporadas ao modelo persistente
depois de determinar:

- finalidade de cada porta;
- relação com a porta principal;
- comportamento Steam/query;
- possibilidade de configuração explícita;
- necessidade de TCP ou UDP;
- comportamento com múltiplas instâncias;
- requisitos de firewall/NAT;
- comportamento em Nodes remotos.

Quando essas informações forem confirmadas experimentalmente, novos
nomes de porta poderão ser adicionados ao bloco sem quebrar o conceito
de alocação por instância.


## Architectural principle

Port allocation is infrastructure state.

O jogo informa quais portas necessita.

O Capivara determina quais portas concretas serão atribuídas.

O banco mantém a reserva.

O runtime consome a configuração.

O sistema operacional fornece a verificação final de ocupação.

Nenhuma dessas camadas isoladamente deve ser considerada suficiente
para determinar a disponibilidade de uma porta.
