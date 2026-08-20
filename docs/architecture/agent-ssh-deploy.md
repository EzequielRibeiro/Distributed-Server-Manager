# Remote Agent SSH Deployment

## Status

Architecture Decision — Planned implementation

## Context

O Capivara DSM possui um Controller central capaz de registrar e administrar Agents remotos.

O Agent remoto não precisa ter o DSM completo previamente instalado. Entretanto, o primeiro bootstrap precisa ser iniciado por algum canal de acesso já disponível no host remoto.

Para hosts Linux, o canal inicial adotado será SSH.

Após a instalação e o enrollment do Agent, SSH deixa de ser parte do canal operacional normal. O Agent passa a se comunicar com o Controller utilizando o protocolo próprio de Agent, incluindo heartbeat autenticado e recebimento de comandos.


## Objective

Fornecer uma CLI administrativa simples para instalar um Agent Linux remoto a partir do Controller:

    cap agent deploy HOST --ssh-user USER

Exemplo:

    cap agent deploy 192.168.15.55 --ssh-user ezequiel

Nesse exemplo:

    Controller: 192.168.15.35
    Agent:      192.168.15.55


## Architectural principle

SSH é utilizado apenas para bootstrap.

O fluxo normal depois da instalação é:

    Controller
        |
        | SSH somente durante o bootstrap
        v
    Remote Host
        |
        | instala Agent
        | faz enrollment
        v
    Capivara Agent
        |
        | heartbeat autenticado
        | comandos do Controller
        | game-data / updates / runtime
        v
    Controller

O Controller não deve depender permanentemente de SSH para administrar o Agent.


## Command syntax

Sintaxe inicial:

    cap agent deploy HOST --ssh-user USER [options]

Opções previstas:

    HOST
        Endereço IPv4, IPv6 ou hostname do host remoto.

    --ssh-user USER
        Usuário utilizado na conexão SSH inicial.

    --ssh-port PORT
        Porta SSH. Padrão: 22.

    --identity-file PATH
        Chave privada SSH utilizada para autenticação.

    --name NAME
        Nome administrativo desejado para o Agent.

    --controller-url URL
        URL pública ou administrativa pela qual o Agent alcança o Controller.
        Quando omitida, a CLI poderá utilizar a URL configurada no Controller.

    --region-id ID
        Region administrativa associada ao Agent.

    --datacenter-id ID
        Datacenter administrativo associado ao Agent.

    --pairing-ttl SECONDS
        Validade do pairing token temporário.

    --json
        Retorna resultado estruturado para automação.


## Authentication policy

Senhas SSH não devem ser fornecidas diretamente na linha de comando.

Não será suportado um parâmetro como:

    --password senha

Isso evita exposição em:

- histórico do shell;
- listagem de processos;
- logs administrativos;
- ferramentas de auditoria;
- scripts compartilhados.

A autenticação SSH deve reutilizar mecanismos padrões do OpenSSH, incluindo:

- chave privada padrão do usuário;
- ssh-agent;
- `--identity-file`;
- mecanismos interativos suportados pelo cliente SSH quando apropriado.


## Host-key verification

A CLI deve preservar a verificação de identidade do servidor SSH.

Por padrão, o Capivara não deve desabilitar `StrictHostKeyChecking` silenciosamente.

Em primeiro contato, o administrador deve ter a oportunidade de validar a fingerprint do host remoto.

O objetivo é impedir que o bootstrap seja enviado inadvertidamente para um host diferente do solicitado.


## Deployment flow

### 1. Validate Controller identity

A CLI confirma que está sendo executada em um Controller ou Hybrid autorizado e determina:

- `controller_id`;
- URL do Controller;
- configuração do banco;
- Region/Datacenter aplicáveis.


### 2. Validate local requirements

Antes da conexão remota, a CLI verifica:

- cliente `ssh` disponível;
- arquivo de identidade, quando informado;
- parâmetros válidos;
- Controller operacional o suficiente para emitir pairing token.


### 3. Test SSH connectivity

A CLI estabelece conexão com:

    USER@HOST

utilizando a porta configurada.

A primeira verificação deve ser não destrutiva e confirmar pelo menos:

- conectividade;
- autenticação;
- sistema operacional compatível;
- presença de shell POSIX;
- disponibilidade de privilégios necessários ao bootstrap.


### 4. Create pairing token

Somente depois que o host remoto passar pelas verificações iniciais, o Controller gera um pairing token temporário.

O token deve:

- pertencer ao Controller correto;
- possuir TTL curto;
- ser de uso único;
- ser associado ao contexto da instalação quando possível;
- ser invalidado após enrollment bem-sucedido.


### 5. Execute remote bootstrap

O Controller utiliza SSH para iniciar no host remoto o bootstrap oficial do Agent.

Conceitualmente, o comando remoto é equivalente a:

    curl -fsSL CONTROLLER_URL/agent/install.sh | sudo bash -s -- \
      --controller-url CONTROLLER_URL \
      --pairing-token TOKEN

O pairing token não deve ser persistido em arquivos permanentes no host remoto.


### 6. Agent enrollment

O instalador registra o novo Agent no Controller utilizando o pairing token.

O enrollment cria a identidade permanente do Agent e entrega as credenciais permanentes necessárias ao protocolo Controller-Agent.


### 7. Agent service starts

Após a instalação, o serviço do Agent inicia no host remoto.

O Agent passa a enviar heartbeat ao Controller utilizando sua credencial permanente.


### 8. Verify online state

A CLI não deve considerar o deployment concluído apenas porque o processo SSH terminou com código zero.

O sucesso exige confirmação no Controller de que:

- pairing token foi consumido;
- Agent foi criado;
- Agent está `active`;
- heartbeat foi recebido;
- health está `online` dentro do timeout previsto.


### 9. Finish SSH bootstrap

Depois que o Agent estiver online, o fluxo administrativo normal deixa de depender do SSH.

Operações posteriores devem utilizar o canal próprio Controller-Agent.


## Expected output

Exemplo de saída humana:

    Capivara Agent Deployment

    Host...................... 192.168.15.55
    SSH user.................. ezequiel
    SSH connectivity.......... OK
    Remote platform........... Linux
    Pairing token............. created
    Agent bootstrap........... OK
    Enrollment................ OK
    Agent heartbeat........... online

    Agent registered
      ID...................... agent-node02
      Host.................... 192.168.15.55
      Status.................. active
      Health.................. online

Em falha, a etapa exata deve ser informada sem expor segredos.


## JSON output

Quando `--json` for utilizado, a saída deverá ser adequada para automação.

Exemplo conceitual:

    {
      "host": "192.168.15.55",
      "ssh_user": "ezequiel",
      "agent_id": "agent-node02",
      "status": "active",
      "health": "online",
      "deployment": "completed"
    }

Segredos, pairing tokens e credenciais permanentes nunca devem aparecer no JSON final.


## Failure behavior

A operação deve falhar de forma segura se ocorrer qualquer uma das condições abaixo:

- host SSH inacessível;
- autenticação SSH recusada;
- fingerprint do host não aceita;
- sistema operacional incompatível;
- ausência de pré-requisito obrigatório;
- ausência de privilégio necessário;
- falha ao emitir pairing token;
- falha no download do bootstrap;
- falha na instalação do Agent;
- enrollment recusado;
- pairing token expirado;
- Agent registrado mas heartbeat não confirmado dentro do timeout.

Uma falha de deployment não deve criar silenciosamente um Agent considerado operacional.


## Retry and idempotency

A CLI deve ser segura para retry.

Antes de instalar, deve verificar se o host já possui um Capivara Agent registrado.

Quando o Agent correspondente já estiver online, o comando deve interromper a reinstalação por padrão e informar o estado encontrado.

Uma reinstalação explícita futura poderá exigir uma opção administrativa específica, por exemplo:

    --reinstall

O comportamento padrão deve favorecer preservação da instalação existente.


## Existing installation protection

O deployment remoto não deve sobrescrever automaticamente:

- identidade permanente do Agent;
- credenciais do Agent;
- game-data existente;
- instâncias hospedadas;
- configuração local administrada;
- dados de runtime persistentes.

Qualquer fluxo de reinstall deve ser tratado como operação administrativa separada e explicitamente solicitada.


## Network requirements

Durante o bootstrap:

    Controller -> Agent : SSH
    Agent -> Controller : HTTP/HTTPS do protocolo Capivara

Depois do bootstrap:

    Agent -> Controller : heartbeat e comunicação operacional

O Agent deve conseguir alcançar a `controller_url` configurada.

Não é necessário manter a porta SSH exposta especificamente para o Capivara depois que o Agent estiver operacional.


## Controller URL

Em redes locais, um exemplo pode ser:

    http://192.168.15.35:8080

Em produção distribuída, recomenda-se HTTPS com um nome DNS estável, por exemplo:

    https://controller.example.net

A URL entregue ao Agent deve ser uma URL que o próprio Agent consiga alcançar, e não apenas um endereço válido do ponto de vista do navegador do administrador.


## Relationship with Agent installation API

A funcionalidade deve reutilizar a infraestrutura já existente de instalação de Agent:

- emissão de pairing token;
- associação a Controller;
- Region/Datacenter;
- enrollment;
- status de instalação;
- confirmação de heartbeat.

`cap agent deploy` é uma camada administrativa de bootstrap remoto sobre esse mecanismo.

Não deve ser criado um segundo modelo de identidade ou pairing apenas para SSH.


## Relationship with game-data

A instalação do Agent é independente da existência de instâncias de clientes.

Depois de registrado e online, o Agent pode receber comandos do Controller para preparar recursos próprios do host, incluindo game-data.

O modelo é:

    Controller = orquestra
    Agent      = executa
    game-data  = recurso pertencente ao Agent
    Instance   = criada posteriormente no Agent escolhido pelo placement

SSH não participa da instalação normal de game-data depois que o Agent está operacional.


## Security requirements

A implementação deve respeitar os seguintes requisitos:

1. Não aceitar senha SSH como argumento de CLI.
2. Não registrar pairing token em logs.
3. Não imprimir credenciais permanentes.
4. Utilizar pairing token de uso único e TTL curto.
5. Preservar verificação de host key SSH.
6. Evitar shell interpolation insegura de parâmetros fornecidos pelo usuário.
7. Construir argumentos SSH como lista estruturada quando implementado em Python.
8. Não utilizar `shell=True` para executar comandos locais com dados do usuário.
9. Tratar retorno SSH diferente de zero como falha.
10. Confirmar heartbeat no Controller antes de declarar deployment completo.
11. Não considerar conectividade SSH como prova de identidade do Agent após enrollment.
12. Depois do bootstrap, utilizar apenas as credenciais permanentes do protocolo do Agent.


## Suggested implementation modules

Para manter a arquitetura modular, a funcionalidade não deve aumentar significativamente `dashboard/server.py`.

Estrutura sugerida:

    bin/cap
        roteamento de CLI

    database/agent_deploy_cli.py
        parsing e apresentação do comando

    core/agent_ssh_deploy.py
        orquestração do bootstrap SSH

    dashboard/agent_installation_api.py
        reaproveitado para pairing e status

    tests/agent_ssh_deploy_test.py
        testes unitários e contratos de segurança


## Test plan

A implementação deverá possuir cobertura para pelo menos:

- parsing da CLI;
- `cap agent deploy HOST --ssh-user USER`;
- porta SSH customizada;
- identity file;
- hostname/IP válidos;
- argumentos inválidos;
- montagem segura do comando SSH;
- ausência de senha em argumentos;
- emissão de pairing somente depois do preflight SSH;
- pairing token não exposto em saída final;
- falha de SSH;
- falha de sudo remoto;
- falha de bootstrap;
- enrollment bem-sucedido;
- timeout de heartbeat;
- Agent já instalado;
- saída `--json` sem segredos;
- integração com SQLite e demais backends suportados pelo repository layer.

Os testes automatizados não devem exigir um host SSH externo real na CI normal. O executor SSH deve ser injetável/mockável para testes determinísticos.

Um teste de integração real poderá existir separadamente para ambientes preparados.


## Initial scope

A primeira versão de `cap agent deploy` terá foco em Agents Linux via OpenSSH.

Windows remoto poderá utilizar posteriormente outro transporte apropriado, como WinRM/OpenSSH, sem alterar o contrato lógico de enrollment do Agent.


## Future work

Possíveis extensões futuras:

- `cap agent deploy --inventory FILE` para múltiplos hosts;
- integração com Ansible;
- cloud-init/bootstrap token;
- discovery de host capabilities antes do deployment;
- deploy paralelo com limites de concorrência;
- jump host / ProxyJump;
- políticas de bastion;
- rotação automática da chave SSH de bootstrap;
- instalação Windows remota;
- confirmação explícita de fingerprint via modo não interativo;
- deploy por APIs de provedores cloud.


## Decision

O Capivara adotará SSH como mecanismo opcional de bootstrap remoto para Agents Linux através da CLI:

    cap agent deploy HOST --ssh-user USER

SSH será apenas o transporte inicial.

Após enrollment e heartbeat confirmado, toda operação normal deverá utilizar o protocolo próprio Controller-Agent.
