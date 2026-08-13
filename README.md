# Capivara Distributed Server Manager

<div align="center">

![Version](https://img.shields.io/badge/version-v1.1.0--dev.1-blue.svg)
![Linux](https://img.shields.io/badge/Linux-Ubuntu%2022.04-orange)
![License](https://img.shields.io/badge/license-GPL%20v3-green)
![Bash](https://img.shields.io/badge/Bash-5.x-black)
![Python](https://img.shields.io/badge/Python-3.x-yellow)

Sistema profissional para gerenciamento de servidores DayZ Linux utilizando LinuxGSM.

</div>

---

# Índice

- Sobre o Projeto
- Principais Recursos
- Arquitetura
- Estrutura de Diretórios
- Instalação
- Organização dos Arquivos
- Dashboard
- Módulos
- Comandos
- Serviços
- Atualização
- Backup
- Troubleshooting
- FAQ
- Roadmap
- Licença

---

# Sobre o Projeto

O **DSM (DayZ Server Manager)** é um sistema modular desenvolvido para facilitar o gerenciamento de servidores DayZ dedicados em Linux.

O projeto foi concebido para atuar como uma camada de administração sobre o LinuxGSM, oferecendo automação, monitoramento, backup, atualização, gerenciamento de mods, notificações e uma interface web integrada.

Todo o sistema foi projetado para ser modular, permitindo expansão por meio de novos componentes sem alterar a arquitetura principal.

---

# Objetivos

O DSM foi desenvolvido com os seguintes objetivos:

- Centralizar a administração do servidor DayZ.
- Automatizar tarefas repetitivas.
- Facilitar atualizações.
- Reduzir tempo de indisponibilidade.
- Fornecer monitoramento em tempo real.
- Integrar notificações.
- Disponibilizar uma Dashboard Web.
- Manter compatibilidade com LinuxGSM.

---

# Principais Recursos

✓ Administração completa do servidor
✓ Atualização automática de Mods
✓ Backup automático
✓ Restauração de backups
✓ Dashboard Web
✓ Monitoramento de CPU
✓ Monitoramento de RAM
✓ Monitoramento de Disco
✓ Load Average
✓ Temperatura do Servidor
✓ Uptime
✓ Watchdog
✓ Reinício Automático
✓ Scheduler
✓ Doctor
✓ Notificações Discord
✓ Notificações Telegram
✓ Update Manager
✓ Integração LinuxGSM
✓ Serviços systemd
✓ Logs centralizados
✓ Arquitetura modular

---

# Filosofia do Projeto

O DSM segue alguns princípios fundamentais:

- Simplicidade de instalação.
- Facilidade de manutenção.
- Organização dos arquivos.
- Código modular.
- Baixa dependência externa.
- Compatibilidade com distribuições Linux baseadas em Debian.
- Atualizações seguras.
- Facilidade para contribuição da comunidade.

---

# Público-alvo

Este projeto é destinado para:

- Administradores de servidores DayZ.
- Comunidades de jogos.
- Clãs.
- Desenvolvedores.
- Hospedagens Linux.
- Usuários LinuxGSM.

---

# Compatibilidade

Distribuições suportadas:

- Ubuntu 20.04
- Ubuntu 22.04
- Ubuntu 24.04
- Debian 11
- Debian 12

Arquitetura:

- x86_64

---

# PARTE 2 — Arquitetura do DSM

---

# Arquitetura Geral

O DSM foi projetado utilizando uma arquitetura modular.

Cada módulo possui responsabilidades específicas, reduzindo o acoplamento entre componentes e facilitando futuras expansões.

A comunicação entre os módulos ocorre através da biblioteca central localizada em:

```text
/opt/dsm/core
```

Todos os comandos executados pelo usuário passam inicialmente pelo comando principal `dsm`, localizado em:

```text
/usr/local/bin/dsm
```

Esse executável apenas encaminha a solicitação para o módulo responsável.

---

# Fluxo Geral

```
                 Usuário
                     │
                     ▼
              /usr/local/bin/dsm
                     │
                     ▼
              /opt/dsm/bin/dsm
                     │
                     ▼
           core/bootstrap.sh
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
   Configuração   Logger      Dispatcher
        │            │            │
        └────────────┼────────────┘
                     ▼
          Seleção do módulo
                     │
 ┌────────┬────────┬────────┬────────┬────────┐
 ▼        ▼        ▼        ▼        ▼
Server   Mods   Backup  Monitor  Dashboard
 │         │        │        │        │
 ▼         ▼        ▼        ▼        ▼
LinuxGSM SteamCMD Arquivos Métricas Interface
```

---

# Componentes

O DSM é composto por onze módulos principais.

```
DSM

├── Core
├── Server
├── Mods
├── Monitor
├── Doctor
├── Backup
├── Scheduler
├── Notification
├── Dashboard
├── Install
└── Update Manager
```

Cada módulo é independente.

Sempre que possível, um módulo não acessa diretamente outro módulo. Em vez disso, utiliza funções comuns disponibilizadas pelo Core.

Essa abordagem reduz dependências e facilita testes e manutenção.

---

# Papel do Core

O diretório:

```text
/opt/dsm/core
```

contém todas as funções compartilhadas pelo sistema.

Entre elas:

- carregamento da configuração;
- inicialização;
- validação do ambiente;
- manipulação de logs;
- tratamento de erros;
- controle de processos;
- biblioteca utilitária.

Nenhum módulo deve reimplementar funcionalidades já existentes no Core.

---

# Bootstrap

O primeiro arquivo executado pelo DSM é:

```text
core/bootstrap.sh
```

Responsabilidades:

- localizar o diretório do DSM;
- validar variáveis obrigatórias;
- carregar `settings.conf`;
- preparar o ambiente;
- carregar bibliotecas;
- inicializar o Logger;
- verificar permissões.

Caso alguma etapa falhe, a execução é interrompida imediatamente.

---

# Arquitetura Modular

Cada módulo possui sua própria estrutura.

Exemplo:

```
monitor/

├── monitor.sh
├── watchdog.sh
├── metrics.sh
├── alerts.sh
└── daemon.sh
```

Outro exemplo:

```
backup/

├── backup.sh
├── restore.sh
├── verify.sh
└── cleanup.sh
```

Essa organização torna o código mais simples de manter e expandir.

---

# Fluxo do Monitor

```
Monitor

       │
       ▼

Coleta Métricas

       │

CPU
RAM
Disco
Load
Temperatura
Uptime

       │
       ▼

Validação de Limites

       │

       ▼

Alerta?

       │

Sim ─────────► Discord

              Telegram

              Dashboard

Não

       │

       ▼

Aguardar próximo ciclo
```

---

# Fluxo do Scheduler

```
Scheduler

        │

        ▼

Lê Agenda

        │

        ▼

Existe tarefa?

        │

Sim

        ▼

Executa

        │

Atualização

Backup

Restart

Doctor

Scripts

        │

        ▼

Grava Histórico
```

---

# Fluxo do Backup

```
Servidor

      │

      ▼

Parada Opcional

      │

      ▼

Compactação

      │

      ▼

Checksum

      │

      ▼

Armazenamento

      │

      ▼

Política de Retenção
```

---

# Fluxo do Dashboard

```
Browser

     │

HTTP

     ▼

Dashboard

     │

API Local

     ▼

DSM

     │

Leitura

Logs

Métricas

Estado

Scheduler

Backup

Mods

     │

JSON

     ▼

Interface Web
```

---

# Comunicação Interna

Todos os módulos utilizam arquivos de configuração centralizados.

```
config/

settings.conf

dashboard.env

Banco SQLite (`data/capivara.db`) para usuários, papéis e vínculos
```

Usuários e senhas não são armazenados em arquivos de configuração. O banco SQLite é a única fonte de verdade, e senhas usam hash `scrypt` com salt individual.

Essa centralização simplifica backups, manutenção e migrações.

---

# Persistência

O DSM grava informações em:

```
logs/
```

para registros operacionais,

```
cache/
```

para dados temporários,

e

```
backups/
```

para cópias de segurança.

Nenhum dado operacional é gravado fora da estrutura principal do DSM, exceto quando explicitamente configurado pelo administrador.

---

# Segurança

Durante a execução, o DSM:

- valida permissões;
- verifica integridade dos arquivos essenciais;
- registra eventos em log;
- evita execução concorrente quando necessário;
- trata falhas antes de prosseguir.

Essa estratégia reduz riscos de corrupção de dados e facilita o diagnóstico de problemas.

---

# Parte 3 — Estrutura de Diretórios do DSM

Esta seção apresenta a estrutura completa de diretórios do **DSM (DayZ Server Manager)**, detalhando a finalidade de cada pasta e a organização recomendada para instalação, manutenção, atualização e realização de backups do sistema.

O DSM utiliza uma estrutura centralizada localizada em:

```
/opt/dsm
```

O diretório `/opt/dsm` é considerado o **diretório raiz operacional do DSM**, onde ficam armazenados os módulos do sistema, arquivos de configuração, logs, dados temporários de execução e componentes necessários para o gerenciamento do servidor DayZ.

A utilização desse caminho segue a recomendação padrão de sistemas Linux, mantendo aplicações adicionais instaladas fora dos diretórios nativos do sistema operacional (`/usr`, `/bin`, `/etc`), facilitando manutenção, remoção e migração do ambiente.

---

## 3.1 Estrutura principal de diretórios

```
/opt/dsm
│
├── bin/
│   └── dsm
│
├── core/
│   ├── bootstrap.sh
│   ├── config.sh
│   ├── logger.sh
│   ├── paths.sh
│   └── utils.sh
│
├── config/
│   ├── dsm.conf
│   ├── server.conf
│   └── discord.conf
│
├── modules/
│   ├── server/
│   ├── backup/
│   ├── update/
│   ├── monitor/
│   ├── metrics/
│   └── dashboard/
│
├── logs/
│   ├── dsm.log
│   ├── server.log
│   └── error.log
│
├── data/
│   ├── cache/
│   ├── state/
│   └── runtime/
│
├── backup/
│   ├── database/
│   ├── configs/
│   └── archives/
│
├── tmp/
│
└── docs/
```

---

## 3.2 Descrição dos diretórios

### `/opt/dsm/bin`

Contém os comandos executáveis disponibilizados pelo DSM.

Exemplo:

```
/opt/dsm/bin/dsm
```

Responsável pela execução dos comandos administrativos:

```
dsm start
dsm stop
dsm restart
dsm status
dsm backup
dsm update
```

Normalmente é criado um link simbólico:

```
/usr/local/bin/dsm -> /opt/dsm/bin/dsm
```

permitindo executar o DSM de qualquer localização no terminal.

---

### `/opt/dsm/core`

Contém os componentes fundamentais do DSM.

Responsável por:

- Inicialização do ambiente;
- Carregamento das configurações;
- Definição dos caminhos internos;
- Sistema de logs;
- Funções auxiliares compartilhadas.

Estrutura:

```
core/
├── bootstrap.sh
├── config.sh
├── logger.sh
├── paths.sh
└── utils.sh
```

O arquivo `bootstrap.sh` deve ser carregado antes da execução dos módulos:

```bash
source /opt/dsm/core/bootstrap.sh
```

---

### `/opt/dsm/config`

Armazena todos os arquivos de configuração do DSM.

Estrutura:

```
config/
├── dsm.conf
├── server.conf
└── discord.conf
```

Contém informações como:

- Nome do servidor;
- Caminho da instalação DayZ;
- Portas utilizadas;
- Configuração Steam Query;
- Configurações de backup;
- Integração Discord;
- Limites de monitoramento.

A separação das configurações permite atualizar o DSM sem perder ajustes personalizados.

---

### `/opt/dsm/modules`

Diretório responsável pelos módulos funcionais do DSM.

Estrutura:

```
modules/
├── server/
├── backup/
├── update/
├── monitor/
├── metrics/
└── dashboard/
```

Cada módulo possui uma finalidade específica:

**server**
- Inicialização do servidor DayZ;
- Parada;
- Reinício;
- Consulta de status.

**backup**
- Criação de backups;
- Restauração;
- Compactação;
- Gerenciamento de arquivos.

**update**
- Atualização do DSM;
- Controle de versões;
- Atualização do servidor.

**monitor**
- Monitoramento do processo DayZ;
- Verificação de disponibilidade;
- Sistema de recuperação.

**metrics**
- CPU;
- Memória RAM;
- Disco;
- Load Average;
- Temperatura;
- Uptime.

**dashboard**
- Exibição das informações coletadas;
- Interface de acompanhamento do servidor.

---

### `/opt/dsm/logs`

Armazena todos os registros de execução do DSM.

Estrutura:

```
logs/
├── dsm.log
├── server.log
└── error.log
```

Utilizado para:

- Diagnóstico de falhas;
- Auditoria;
- Histórico de operações;
- Análise de problemas.

---

### `/opt/dsm/data`

Armazena informações internas de funcionamento.

Estrutura:

```
data/
├── cache/
├── state/
└── runtime/
```

Utilizado para:

- Controle de processos;
- Estado atual do DSM;
- Dados temporários;
- Informações auxiliares.

---

### `/opt/dsm/backup`

Diretório destinado aos backups.

Estrutura:

```
backup/
├── database/
├── configs/
└── archives/
```

Armazena:

- Configurações;
- Arquivos críticos;
- Pacotes compactados;
- Cópias de segurança.

---

### `/opt/dsm/tmp`

Diretório temporário utilizado durante operações internas.

Pode armazenar arquivos durante:

- Atualizações;
- Downloads;
- Compactações;
- Restaurações.

Após o término das operações, os arquivos temporários devem ser removidos automaticamente.

---

### `/opt/dsm/docs`

Armazena documentação do projeto.

Exemplo:

- Manual de instalação;
- Guia administrativo;
- Histórico de versões;
- Procedimentos operacionais.

---

# 3.3 Organização de manutenção

A estrutura modular permite:

- Atualização independente dos componentes;
- Preservação das configurações;
- Facilidade de diagnóstico;
- Backups seletivos;
- Migração simplificada.

Exemplo de backup das configurações:

```bash
tar -czf dsm-config-backup.tar.gz /opt/dsm/config
```

Backup completo:

```bash
tar -czf dsm-full-backup.tar.gz /opt/dsm
```

---

# 3.4 Remoção segura do DSM

Como todos os arquivos ficam centralizados em:

```
/opt/dsm
```

a remoção do DSM pode ser realizada sem alterar arquivos do sistema operacional.

Processo recomendado:

1. Parar o serviço:

```bash
dsm stop
```

2. Remover o link de execução:

```bash
rm /usr/local/bin/dsm
```

3. Remover o diretório principal:

```bash
rm -rf /opt/dsm
```

---

# 3.5 Considerações finais

A estrutura `/opt/dsm` foi projetada para oferecer uma instalação organizada, modular e segura.

A separação entre:

- Código;
- Configurações;
- Dados;
- Logs;
- Backups;

permite que o DSM seja atualizado, migrado ou restaurado com segurança.

Essa arquitetura também possibilita futuras expansões do projeto, permitindo a inclusão de novos módulos sem alterar a estrutura principal do sistema.

# Parte 4 — Instalação Completa do DSM

Esta seção descreve o processo completo de instalação do **DSM (DayZ Server Manager)** em um ambiente Linux.

O procedimento foi desenvolvido para realizar uma instalação organizada, segura e padronizada, preparando todos os componentes necessários para o gerenciamento do servidor DayZ.

A instalação contempla:

- Preparação do sistema operacional;
- Instalação das dependências;
- Criação da estrutura de diretórios;
- Configuração das permissões;
- Instalação dos módulos DSM;
- Configuração inicial;
- Validação da instalação.

---

# 4.1 Requisitos do sistema

Antes de iniciar a instalação, certifique-se de que o servidor atende aos requisitos mínimos.

## Sistema operacional recomendado

```
Ubuntu Server 22.04 LTS
```

Também pode funcionar em distribuições baseadas em Debian:

```
Debian 11+
Linux Mint Server
Ubuntu Server 24.04 LTS
```

---

## Requisitos mínimos recomendados

```
CPU:
- 4 núcleos

Memória:
- 8 GB RAM

Armazenamento:
- 50 GB livres

Rede:
- Conexão estável com internet
```

Para servidores DayZ maiores, recomenda-se:

```
CPU:
- 6 a 8 núcleos

Memória:
- 16 GB RAM ou superior

Armazenamento:
- SSD/NVMe
```

---

# 4.2 Atualização do sistema

Antes da instalação do DSM, atualize os pacotes do sistema:

```bash
sudo apt update
sudo apt upgrade -y
```

Instale ferramentas básicas:

```bash
sudo apt install -y \
curl \
wget \
git \
nano \
tar \
gzip \
unzip \
htop \
net-tools
```

---

# 4.3 Instalação das dependências

O DSM utiliza ferramentas padrão do Linux.

Instale:

```bash
sudo apt install -y \
bash \
procps \
util-linux \
systemd \
cron
```

Verifique a versão do Bash:

```bash
bash --version
```

O DSM requer:

```
Bash 5.x ou superior
```

---

# 4.4 Criação do usuário do servidor

Recomenda-se executar o servidor DayZ utilizando um usuário dedicado.

Criar usuário:

```bash
sudo adduser dayz
```

Adicionar permissões:

```bash
sudo usermod -aG sudo dayz
```

Alterar para o usuário:

```bash
su - dayz
```

---

# 4.5 Criação da estrutura DSM

O DSM será instalado em:

```
/opt/dsm
```

Criar diretório principal:

```bash
sudo mkdir -p /opt/dsm
```

Definir proprietário:

```bash
sudo chown -R dayz:dayz /opt/dsm
```

Criar estrutura interna:

```bash
mkdir -p /opt/dsm/{bin,core,config,modules,logs,data,backup,tmp,docs}
```

Resultado:

```
/opt/dsm
│
├── bin
├── core
├── config
├── modules
├── logs
├── data
├── backup
├── tmp
└── docs
```

---

# 4.6 Instalação dos arquivos DSM

Copiar os arquivos do projeto:

Exemplo:

```bash
cp -r DSM/core/* /opt/dsm/core/
cp -r DSM/modules/* /opt/dsm/modules/
cp -r DSM/config/* /opt/dsm/config/
cp -r DSM/bin/* /opt/dsm/bin/
```

A estrutura final deverá ser:

```
/opt/dsm

├── bin/
│   └── dsm

├── core/
│   ├── bootstrap.sh
│   ├── config.sh
│   └── utils.sh

├── config/
│   ├── dsm.conf
│   └── server.conf

├── modules/
│   ├── server/
│   ├── backup/
│   ├── monitor/
│   ├── metrics/
│   └── dashboard/
```

---

# 4.7 Configuração das permissões

Aplicar permissões corretas:

```bash
chmod +x /opt/dsm/bin/dsm
```

Permissões dos scripts:

```bash
find /opt/dsm -name "*.sh" -exec chmod +x {} \;
```

Garantir proprietário:

```bash
sudo chown -R dayz:dayz /opt/dsm
```

---

# 4.8 Configuração do arquivo principal

O arquivo principal de configuração é:

```
/opt/dsm/config/dsm.conf
```

Exemplo:

```ini
DSM_NAME="DayZ Server Manager"
DSM_ROOT="/opt/dsm"
SERVER_NAME="dayzserver"
SERVER_PATH="/home/dayz/server"
BACKUP_PATH="/opt/dsm/backup"
LOG_PATH="/opt/dsm/logs"
```

---

# 4.9 Configuração do servidor DayZ

Editar:

```
/opt/dsm/config/server.conf
```

Exemplo:

```ini
SERVER_NAME="dayzserver"
SERVER_PORT=2302
STEAM_QUERY_PORT=27016
MAX_PLAYERS=60
START_DELAY=10
```

---

# 4.10 Instalação do comando DSM global

Criar link simbólico:

```bash
sudo ln -s /opt/dsm/bin/dsm /usr/local/bin/dsm
```

Testar:

```bash
dsm --help
```

Resultado esperado:

```
DSM - DayZ Server Manager

Commands:

start
stop
restart
status
backup
update
monitor
```

---

# 4.11 Inicialização do ambiente DSM

Antes de utilizar os módulos:

```bash
source /opt/dsm/core/bootstrap.sh
```

Validar:

```bash
echo $DSM_ROOT
```

Resultado esperado:

```
/opt/dsm
```

---

# 4.12 Primeiro teste do DSM

Executar:

```bash
dsm status
```

Exemplo de retorno:

```
DSM Status

Sistema:
OK

Servidor DayZ:
STOPPED

Monitor:
ACTIVE

Backup:
READY
```

---

# 4.13 Teste de inicialização do servidor

Executar:

```bash
dsm start
```

Verificar:

```bash
dsm status
```

Resultado esperado:

```
Servidor DayZ:
RUNNING
```

---

# 4.14 Configuração de inicialização automática

Criar serviço systemd:

```bash
sudo nano /etc/systemd/system/dsm.service
```

Conteúdo:

```ini
[Unit]
Description=DayZ Server Manager
After=network.target

[Service]
Type=simple
User=dayz
WorkingDirectory=/opt/dsm
ExecStart=/usr/local/bin/dsm monitor
Restart=always

[Install]
WantedBy=multi-user.target
```

Ativar serviço:

```bash
sudo systemctl daemon-reload
```

Habilitar inicialização:

```bash
sudo systemctl enable dsm
```

Iniciar:

```bash
sudo systemctl start dsm
```

---

# 4.15 Validação final da instalação

Executar:

```bash
dsm status
```

Validar:

```
[ OK ] Estrutura DSM encontrada
[ OK ] Configuração carregada
[ OK ] Logs funcionando
[ OK ] Módulos disponíveis
[ OK ] Monitor ativo
[ OK ] Sistema pronto
```

---

# 4.16 Solução de problemas comuns

## DSM_ROOT não definido

Erro:

```
DSM_ROOT não definido - não é possível inicializar o DSM
```

Solução:

```bash
export DSM_ROOT=/opt/dsm
```

Ou carregue novamente:

```bash
source /opt/dsm/core/bootstrap.sh
```

---

## Permissão negada

Erro:

```
Permission denied
```

Solução:

```bash
chmod +x arquivo.sh
```

---

## Comando DSM não encontrado

Verificar:

```bash
which dsm
```

Esperado:

```
/usr/local/bin/dsm
```

Recriar:

```bash
sudo ln -s /opt/dsm/bin/dsm /usr/local/bin/dsm
```

---

# 4.17 Conclusão

Após a conclusão desta etapa, o DSM estará instalado e preparado para:

- Gerenciar o servidor DayZ;
- Monitorar processos;
- Executar backups;
- Controlar atualizações;
- Coletar métricas;
- Operar o Dashboard;
- Enviar alertas administrativos.

A instalação foi projetada para manter separação entre código, configuração e dados, permitindo manutenção e expansão futura do projeto.

# Parte 5 — Dashboard Web

O Dashboard Web do **DSM (DayZ Server Manager)** é responsável pela visualização centralizada das informações operacionais do servidor DayZ.

Ele permite acompanhar em tempo real o estado do servidor, consumo de recursos, métricas do sistema, alertas e informações administrativas.

O Dashboard foi desenvolvido para fornecer uma visão rápida da saúde do ambiente sem necessidade de acesso direto ao terminal Linux.

---

# 5.1 Objetivos do Dashboard

O Dashboard tem como objetivos:

- Monitoramento visual do servidor;
- Exibição de métricas em tempo real;
- Identificação rápida de problemas;
- Controle operacional;
- Visualização de alertas;
- Auxílio na administração do servidor.

---

# 5.2 Arquitetura do Dashboard

A arquitetura segue o modelo:

```
Usuário
   |
   |
Navegador Web
   |
   |
Dashboard DSM
   |
   |
API / Metrics Module
   |
   |
Sistema Linux
   |
   |
Servidor DayZ
```

---

# 5.3 Estrutura do módulo Dashboard

Localização:

```
/opt/dsm/modules/dashboard
```

Estrutura:

```
dashboard/

├── index.html

├── assets/
│   ├── css/
│   ├── js/
│   └── images/

├── api/

├── config/

└── templates/
```

---

# 5.4 Componentes exibidos

O Dashboard apresenta:

## Status do servidor

Exemplo:

```
Servidor:
ONLINE

Processo:
RUNNING

Uptime:
12 dias 04:35:22
```

---

## Métricas do sistema

Informações coletadas pelo módulo Metrics:

```
CPU:
45%

RAM:
62%

Disco:
71%

Load Average:
1.25

Temperatura:
54°C
```

---

## Informações DayZ

Exibe:

```
Servidor:
dayzserver

Jogadores:
34/60

Porta:
2302

Processo:
Ativo
```

---

## Monitoramento de processos

Exemplo:

```
PID:
23541

Processo:
DayZServer_x64

Estado:
RUNNING
```

---

# 5.5 Alertas

O Dashboard apresenta alertas:

Exemplo:

```
[ALERTA]
CPU acima de 90%
Data:
27/07/2026
Ação:
Verificar processos
```

Tipos:

- CPU alta;
- Memória insuficiente;
- Disco cheio;
- Servidor offline;
- Falha de inicialização.

---

# 5.6 Atualização das informações

O Dashboard utiliza atualização periódica.

Exemplo:

```
Intervalo:
5 segundos
```

Fluxo:

```
Metrics
   |
   |
Coleta dados
   |
   |
API DSM
   |
   |
Dashboard
   |
   |
Atualização visual
```

---

# 5.7 Integração com Discord

O Dashboard pode utilizar o módulo Discord para notificações.

Exemplo:

```
Servidor iniciado
Servidor parado
Falha detectada
Backup concluído
```

---

# 5.8 Segurança

Recomendações:

- Executar atrás de firewall;
- Utilizar autenticação;
- Não expor portas administrativas;
- Utilizar HTTPS em produção.

---

# 5.9 Inicialização do Dashboard

Executar:

```bash
dsm dashboard start
```

Verificar:

```bash
dsm dashboard status
```

Parar:

```bash
dsm dashboard stop
```

---

# 5.10 Conclusão

O Dashboard Web transforma o DSM em uma plataforma completa de administração visual, permitindo acompanhar o servidor DayZ de forma simples, rápida e eficiente.

# Parte 6 — Módulos do DSM

O DSM possui uma arquitetura modular, permitindo adicionar, atualizar ou remover funcionalidades sem alterar o núcleo do sistema.

Cada módulo possui responsabilidade específica e trabalha integrado ao Core DSM.

---

# 6.1 Estrutura dos módulos

Localização:

```
/opt/dsm/modules
```

Estrutura:

```
modules/
├── server/
├── backup/
├── update/
├── monitor/
├── metrics/
├── dashboard/
└── discord/
```

---

# 6.2 Módulo Server

Responsável pelo gerenciamento do servidor DayZ.

Local:

```
modules/server
```

Funções:

- Iniciar servidor;
- Parar servidor;
- Reiniciar servidor;
- Consultar status;
- Controlar processo.

Exemplos:

```bash
dsm start
```

```bash
dsm stop
```

---

# 6.3 Módulo Backup

Responsável pela proteção dos dados.

Local:

```
modules/backup
```

Funções:

- Backup automático;
- Backup manual;
- Compactação;
- Restauração.

Arquivos protegidos:

```
Configurações
Mods
Banco de dados
Logs
Arquivos críticos
```

Exemplo:

```bash
dsm backup create
```

---

# 6.4 Módulo Update

Responsável pelas atualizações.

Local:

```
modules/update
```

Funções:

- Atualizar DSM;
- Atualizar servidor;
- Controlar versões;
- Aplicar correções.

Exemplo:

```bash
dsm update
```

---

# 6.5 Módulo Monitor

Responsável pelo acompanhamento automático.

Local:

```
modules/monitor
```

Funções:

- Verificar processo DayZ;
- Detectar falhas;
- Reiniciar automaticamente;
- Gerar alertas.

Exemplo:

```
Servidor caiu
↓
Monitor detecta
↓
Executa recuperação
↓
Envia alerta
```

---

# 6.6 Módulo Metrics

Responsável pela coleta de métricas.

Local:

```
modules/metrics
```

Informações coletadas:

```
CPU %
RAM %
Disco %
Load Average
Temperatura
Uptime
Processos
```

Exemplo:

```bash
dsm metrics
```

---

# 6.7 Módulo Dashboard

Responsável pela interface Web.

Local:

```
modules/dashboard
```

Funções:

- Exibição gráfica;
- Monitoramento;
- Indicadores;
- Alertas.

---

# 6.8 Módulo Discord

Responsável pela comunicação externa.

Local:

```
modules/discord
```

Funções:

- Envio de mensagens;
- Alertas;
- Status do servidor;
- Eventos administrativos.

Exemplo:

```
DSM:
Servidor iniciado com sucesso.
```

---

# 6.9 Comunicação entre módulos

Arquitetura:

```
              CORE

               |

 --------------------------------
 |        |        |        |
Server Backup Monitor Metrics

               |

          Dashboard

               |

            Discord
```

---

# 6.10 Expansão futura

A arquitetura permite adicionar:

- Sistema de usuários;
- Controle de permissões;
- API REST;
- Aplicativo Mobile;
- Integração Steam;
- Sistema avançado de logs.

---

# 6.11 Conclusão

A arquitetura modular torna o DSM flexível, permitindo evolução contínua sem comprometer a estabilidade do sistema.

# Parte 7 — Comandos DSM

O DSM disponibiliza uma interface de comandos para administração rápida do servidor DayZ.

O comando principal é:

```bash
dsm
```

---

# 7.1 Ajuda

Exibe todos os comandos disponíveis.

```bash
dsm help
```

Exemplo:

```
DSM - DayZ Server Manager

Commands:

start
stop
restart
status
backup
update
monitor
metrics
dashboard
```

---

# 7.2 Iniciar servidor

Comando:

```bash
dsm start
```

Função:

- Inicia o servidor DayZ;
- Registra logs;
- Atualiza status.

---

# 7.3 Parar servidor

Comando:

```bash
dsm stop
```

Função:

- Finaliza o processo;
- Executa encerramento seguro.

---

# 7.4 Reiniciar servidor

Comando:

```bash
dsm restart
```

Executa:

```
STOP
↓
START
```

---

# 7.5 Consultar status

Comando:

```bash
dsm status
```

Exemplo:

```
DSM:
ONLINE

Servidor DayZ:
RUNNING

Monitor:
ACTIVE
```

---

# 7.6 Backup

Criar backup:

```bash
dsm backup
```

Ver backups:

```bash
dsm backup list
```

Restaurar:

```bash
dsm backup restore
```

---

# 7.7 Atualização

Executar atualização:

```bash
dsm update
```

Atualiza:

- DSM;
- Módulos;
- Componentes.

---

# 7.8 Monitoramento

Ativar monitor:

```bash
dsm monitor start
```

Status:

```bash
dsm monitor status
```

Parar:

```bash
dsm monitor stop
```

---

# 7.9 Métricas

Consultar recursos:

```bash
dsm metrics
```

Exemplo:

```
CPU: 40%
RAM: 55%
DISK: 60%
TEMP: 50°C
```

---

# 7.10 Dashboard

Iniciar:

```bash
dsm dashboard start
```

Status:

```bash
dsm dashboard status
```

Parar:

```bash
dsm dashboard stop
```

---

# 7.11 Logs

Visualizar logs:

```bash
dsm logs
```

Limpar logs antigos:

```bash
dsm logs clean
```

---

# 7.12 Diagnóstico

Executar:

```bash
dsm diagnose
```

Verifica:

- Permissões;
- Configurações;
- Processos;
- Dependências.

---

# 7.13 Lista rápida de comandos

| Comando | Função |
|---|---|
| dsm start | Iniciar servidor |
| dsm stop | Parar servidor |
| dsm restart | Reiniciar servidor |
| dsm status | Status geral |
| dsm backup | Backup |
| dsm update | Atualização |
| dsm monitor | Monitoramento |
| dsm metrics | Métricas |
| dsm dashboard | Dashboard |
| dsm diagnose | Diagnóstico |

---

# 7.14 Conclusão

Os comandos DSM fornecem uma interface simples e padronizada para administrar todo o ambiente DayZ.

Com poucos comandos é possível controlar:

- Servidor;
- Backups;
- Monitoramento;
- Atualizações;
- Métricas;
- Dashboard.

# Parte 8 — Serviços Systemd

O DSM utiliza o **Systemd** como gerenciador de serviços do Linux para garantir inicialização automática, monitoramento e recuperação dos componentes principais do sistema.

A integração com Systemd permite que o DSM opere como um serviço permanente do servidor.

---

# 8.1 Objetivos do serviço Systemd

O serviço Systemd é responsável por:

- Inicializar o DSM automaticamente;
- Executar o monitoramento contínuo;
- Reiniciar serviços em caso de falha;
- Controlar o ciclo de vida do DSM;
- Integrar com o sistema operacional.

---

# 8.2 Localização dos arquivos Systemd

Os arquivos ficam localizados em:

```
/etc/systemd/system/
```

Exemplo:

```
/etc/systemd/system/dsm.service
```

---

# 8.3 Serviço principal DSM

Arquivo:

```
dsm.service
```

Conteúdo:

```ini
[Unit]
Description=DayZ Server Manager
After=network.target

[Service]
Type=simple
User=dayz
WorkingDirectory=/opt/dsm
ExecStart=/usr/local/bin/dsm monitor
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

# 8.4 Recarregar serviços

Após criar ou alterar arquivos Systemd:

```bash
sudo systemctl daemon-reload
```

---

# 8.5 Ativar inicialização automática

Habilitar DSM:

```bash
sudo systemctl enable dsm
```

---

# 8.6 Iniciar serviço

Executar:

```bash
sudo systemctl start dsm
```

---

# 8.7 Parar serviço

Executar:

```bash
sudo systemctl stop dsm
```

---

# 8.8 Reiniciar serviço

Executar:

```bash
sudo systemctl restart dsm
```

---

# 8.9 Verificar status

Comando:

```bash
systemctl status dsm
```

Exemplo:

```
● dsm.service
Active:
active (running)
Process:
monitor.sh
Status:
OK
```

---

# 8.10 Logs Systemd

Visualizar logs:

```bash
journalctl -u dsm
```

Últimas mensagens:

```bash
journalctl -u dsm -n 100
```

Modo acompanhamento:

```bash
journalctl -u dsm -f
```

---

# 8.11 Recuperação automática

O DSM utiliza:

```ini
Restart=always
```

Caso o processo seja encerrado inesperadamente:

```
Falha detectada
↓
Systemd reinicia DSM
↓
Monitor volta a funcionar
```

---

# 8.12 Conclusão

A integração com Systemd garante que o DSM permaneça disponível mesmo após reinicializações ou falhas inesperadas do ambiente Linux.

# Parte 9 — Sistema de Atualização

O sistema de atualização do DSM foi projetado para manter o gerenciador sempre atualizado sem comprometer configurações existentes.

O processo separa:

- Código;
- Configurações;
- Dados;
- Backups.

---

# 9.1 Objetivos

O sistema de atualização permite:

- Atualizar módulos DSM;
- Aplicar correções;
- Controlar versões;
- Restaurar versões anteriores.

---

# 9.2 Estrutura de atualização

Local:

```
/opt/dsm/modules/update
```

Estrutura:

```
update/
├── update.sh
├── version.sh
├── rollback.sh
└── packages/
```

---

# 9.3 Verificar versão atual

Comando:

```bash
dsm version
```

Exemplo:

```
DSM Version:
1.0.0
```

---

# 9.4 Atualização manual

Executar:

```bash
dsm update
```

Processo:

```
Verificar versão
↓
Criar backup
↓
Baixar atualização
↓
Aplicar arquivos
↓
Validar instalação
```

---

# 9.5 Backup antes da atualização

Antes da atualização:

```
/opt/dsm/backup/update/
```

Exemplo:

```
backup/
└── update/
    └── DSM-1.0.0.tar.gz
```

---

# 9.6 Atualização dos módulos

Exemplo:

```
Atualizando:
CORE ........ OK
SERVER ...... OK
MONITOR ..... OK
METRICS ..... OK
DASHBOARD ... OK
```

---

# 9.7 Rollback

Caso ocorra falha:

```bash
dsm rollback
```

Processo:

```
Falha
↓
Restaurar backup
↓
Recarregar módulos
↓
Validar DSM
```

---

# 9.8 Controle de versões

Formato:

```
MAJOR.MINOR.PATCH
```

Exemplo:

```
1.0.0
```

Significado:

```
1 = versão principal
0 = novos recursos
0 = correções
```

---

# 9.9 Boas práticas

Antes de atualizar:

- Realizar backup;
- Parar servidor DayZ;
- Verificar espaço disponível;
- Conferir logs.

---

# 9.10 Conclusão

O sistema de atualização permite evolução contínua do DSM mantendo segurança e estabilidade operacional.

# Parte 10 — Troubleshooting

Esta seção apresenta problemas comuns encontrados durante utilização do DSM e suas soluções.

---

# 10.1 DSM não inicia

Sintoma:

```
DSM não responde
```

Verificar serviço:

```bash
systemctl status dsm
```

Verificar logs:

```bash
journalctl -u dsm
```

---

# 10.2 Erro DSM_ROOT não definido

Mensagem:

```
DSM_ROOT não definido
```

Solução:

```bash
export DSM_ROOT=/opt/dsm
```

Ou:

```bash
source /opt/dsm/core/bootstrap.sh
```

---

# 10.3 Comando dsm não encontrado

Erro:

```
command not found
```

Verificar:

```bash
which dsm
```

Criar link:

```bash
sudo ln -s /opt/dsm/bin/dsm /usr/local/bin/dsm
```

---

# 10.4 Permissão negada

Erro:

```
Permission denied
```

Corrigir:

```bash
chmod +x arquivo.sh
```

Aplicar:

```bash
chmod -R +x /opt/dsm
```

---

# 10.5 Servidor DayZ não inicia

Verificar:

```
Processo DayZ
Configuração
Portas
Logs
```

Comandos:

```bash
dsm status
```

```bash
dsm logs
```

---

# 10.6 Monitor reiniciando servidor constantemente

Verificar:

```
CPU
RAM
Arquivos corrompidos
Configuração
```

Consultar:

```bash
dsm metrics
```

---

# 10.7 Dashboard offline

Verificar:

```bash
dsm dashboard status
```

Reiniciar:

```bash
dsm dashboard restart
```

---

# 10.8 Disco cheio

Verificar:

```bash
df -h
```

Limpar:

```bash
dsm logs clean
```

---

# 10.9 Diagnóstico completo

Executar:

```bash
dsm diagnose
```

O DSM verificará:

- Estrutura;
- Permissões;
- Configuração;
- Serviços;
- Processos.

---

# 10.10 Coleta de informações para suporte

Enviar:

```
Versão DSM
Logs
Status
Configuração
Mensagens de erro
```

---

# 10.11 Conclusão

O Troubleshooting permite identificar rapidamente falhas e manter o servidor DayZ funcionando com estabilidade.

# Parte 11 — FAQ

Perguntas frequentes sobre o DSM.

---

# O que é o DSM?

O DSM é um gerenciador completo para servidores DayZ Linux.

Ele permite:

- Controle do servidor;
- Monitoramento;
- Backup;
- Atualizações;
- Dashboard.

---

# Onde o DSM é instalado?

Diretório padrão:

```
/opt/dsm
```

---

# Preciso executar como root?

Não.

O recomendado é utilizar usuário dedicado:

```
dayz
```

---

# O DSM inicia automaticamente?

Sim.

Utilizando Systemd:

```
dsm.service
```

---

# Posso migrar o DSM para outro servidor?

Sim.

Basta copiar:

```
/opt/dsm
```

e restaurar configurações.

---

# O DSM suporta múltiplos servidores?

A arquitetura permite expansão futura para múltiplas instâncias.

---

# Onde ficam os logs?

Local:

```
/opt/dsm/logs
```

---

# Onde ficam os backups?

Local:

```
/opt/dsm/backup
```

---

# Posso adicionar novos módulos?

Sim.

A arquitetura modular permite novos componentes.

---

# Como atualizar?

Executar:

```bash
dsm update
```

---

# Como verificar problemas?

Executar:

```bash
dsm diagnose
```

---

# Conclusão

O DSM foi desenvolvido para ser simples de administrar, modular e expansível.

# Parte 12 — Roadmap, Contribuição e Licença

Esta seção apresenta o planejamento futuro do DSM, regras de contribuição e informações de licença.

---

# 12.1 Roadmap

## Versão 1.0.0

Status:

```
Concluído
```

Recursos:

- Core DSM;
- Estrutura modular;
- Gerenciamento DayZ;
- Backup;
- Monitor;
- Metrics;
- Dashboard;
- Discord.

---

# Versão 1.1.0

Em desenvolvimento:

- Melhorias no Dashboard;
- Sistema avançado de alertas;
- Melhor gerenciamento de logs;
- API REST;
- Persistência SQLite e migrações versionadas.

---

# Versão 1.2.0

Planejado:

- Controle multi-servidor;
- Usuários administrativos;
- Controle de permissões;
- Histórico de eventos.

---

# Versão 2.0.0

Planejado:

- Aplicação Mobile;
- Integração Steam;
- Inteligência operacional;
- Alta disponibilidade.

---

# 12.2 Contribuição

Contribuições são bem-vindas.

Processo recomendado:

```
1 - Criar Fork
2 - Criar Branch
3 - Implementar alteração
4 - Testar
5 - Enviar Pull Request
```

---

# 12.3 Padrões de desenvolvimento

Recomendações:

- Código documentado;
- Scripts compatíveis com Bash;
- Alterações testadas;
- Manter compatibilidade.

---

# 12.4 Relatórios de problemas

Ao reportar problemas informar:

```
Versão DSM
Sistema operacional
Logs
Descrição do erro
Passos para reprodução
```

---

# 12.5 Licença

O DSM utiliza licença:

```
MIT License
```

Permissões:

- Uso comercial;
- Modificação;
- Distribuição;
- Uso privado.

Condições:

- Manter aviso de copyright;
- Incluir licença original.

---

# 12.6 Direitos

O projeto DSM é distribuído "como está", sem garantias explícitas.

O usuário é responsável pela utilização em ambientes de produção.

---

# 12.7 Conclusão

O DSM foi desenvolvido com foco em:

- Organização;
- Automação;
- Segurança;
- Facilidade de administração;
- Evolução contínua.

A arquitetura permite que o projeto cresça mantendo estabilidade e simplicidade.
