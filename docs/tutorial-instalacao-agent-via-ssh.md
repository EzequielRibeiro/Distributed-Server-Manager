# Tutorial — Instalar um Agent Linux remotamente via SSH

Este tutorial prepara o Controller para instalar um Agent Linux pela página **Infraestrutura → Adicionar Agent → Instalar remotamente via SSH**.

## Como o fluxo funciona

A Dashboard não recebe nem armazena senha SSH. O serviço `dsm-dashboard` conecta ao host remoto usando a chave privada da conta que executa a Dashboard, valida o host e exige `sudo` não interativo. Depois do bootstrap e do enrollment, SSH deixa de ser o canal operacional; o Agent passa a usar o protocolo autenticado do Capivara.

## Preparação simplificada (recomendada)

No Controller, execute uma única vez para cada usuário/host remoto:

```bash
sudo cap agent ssh-prepare mine@192.168.15.55
```

Para uma porta SSH diferente:

```bash
sudo cap agent ssh-prepare mine@192.168.15.55 --ssh-port 2222
```

O assistente descobre a conta do serviço `dsm-dashboard`, cria ou preserva sua chave padrão `id_ed25519`, registra e valida a chave do host, copia a chave pública e instala uma regra sudoers limitada aos dois comandos necessários pelo bootstrap. A senha SSH e a senha de sudo do host remoto podem ser solicitadas uma vez pelos próprios programas `ssh` e `sudo`; elas não são recebidas, armazenadas ou registradas pelo Capivara.

Somente prossiga para a Dashboard quando o comando terminar com:

```text
SSH_READY mine@192.168.15.55
```

As etapas manuais abaixo permanecem como referência e alternativa para diagnóstico.

## 1. Identificar a conta da Dashboard

No Controller:

```bash
systemctl show dsm-dashboard.service -p User --value
```

Nos exemplos abaixo a conta retornada é `capivara`. Confirme o diretório pessoal cadastrado:

```bash
getent passwd capivara
```

Se o diretório pessoal for inexistente, configure um diretório persistente:

```bash
sudo usermod -d /var/lib/capivara capivara
sudo install -d -m 750 -o capivara -g capivara /var/lib/capivara
```

## 2. Criar a chave SSH do serviço

Use o nome padrão `id_ed25519`, reconhecido automaticamente pelo OpenSSH:

```bash
DSM_SERVICE_ACCOUNT="capivara"
DSM_SERVICE_HOME="$(getent passwd "$DSM_SERVICE_ACCOUNT" | cut -d: -f6)"

sudo install -d -m 700 \
  -o "$DSM_SERVICE_ACCOUNT" \
  -g "$DSM_SERVICE_ACCOUNT" \
  "$DSM_SERVICE_HOME/.ssh"

sudo -u "$DSM_SERVICE_ACCOUNT" ssh-keygen \
  -t ed25519 \
  -f "$DSM_SERVICE_HOME/.ssh/id_ed25519" \
  -N ""
```

Nunca copie a chave privada para o Agent nem para a Dashboard.

## 3. Autorizar a chave no Agent

Neste exemplo, o Agent é `192.168.15.55` e o usuário administrativo é `mine`:

```bash
sudo -u capivara ssh-copy-id \
  -i "$DSM_SERVICE_HOME/.ssh/id_ed25519.pub" \
  mine@192.168.15.55
```

Esse comando solicita a senha SSH de `mine` uma única vez para instalar a chave pública.

## 4. Autorizar somente o sudo necessário

Conecte-se ao Agent:

```bash
ssh mine@192.168.15.55
```

O preflight usa `/usr/bin/true` e o bootstrap envia um programa temporário para `/usr/bin/python3 -`. Crie a regra:

```bash
printf '%s\n' \
  'mine ALL=(root) NOPASSWD: /usr/bin/true, /usr/bin/python3 -' \
  | sudo tee /etc/sudoers.d/capivara-agent >/dev/null

sudo chmod 440 /etc/sudoers.d/capivara-agent
sudo visudo -cf /etc/sudoers.d/capivara-agent
```

Confirme os caminhos com `command -v true` e `command -v python3`; ajuste a regra se a distribuição usar caminhos diferentes.

## 5. Validar a conexão a partir do Controller

```bash
sudo -u capivara ssh \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  mine@192.168.15.55 \
  'sudo -n true && echo SSH_OK'
```

O resultado obrigatório é `SSH_OK`. Não prossiga enquanto houver solicitação de senha, erro de chave pública, host key ou `sudo` interativo.

## 6. Instalar pela Dashboard

1. Abra **Infraestrutura → Adicionar Agent**.
2. Selecione **Linux** e **Instalar remotamente via SSH**.
3. Informe host, usuário SSH, porta e URL do Controller alcançável pelo Agent.
4. Selecione Controller, Região e Datacenter.
5. Opcionalmente informe nome administrativo e faixa de portas.
6. Clique em **Instalar Agent via SSH** e acompanhe o diagnóstico abaixo do botão.

O Agent precisa conseguir acessar a URL informada. Endereços como `localhost` ou `127.0.0.1` não funcionam para outro host.

## Solução de problemas

- `Permission denied (publickey)`: a chave pública não está em `~mine/.ssh/authorized_keys` ou a Dashboard usa outra conta.
- `Host key verification failed`: faça a validação manual do passo 5 com `StrictHostKeyChecking=accept-new`.
- `sudo: interactive authentication is required`: revise `/etc/sudoers.d/capivara-agent` e valide com `visudo -cf`.
- `Connection timed out/refused`: confirme IP, porta 22, firewall e serviço SSH do Agent.
- `controller_url`: confirme que o Agent alcança `/agent/install.sh` na URL informada.
- Agent já instalado: o bootstrap recusa reinstalação automática para preservar a identidade existente.

## Segurança e remoção do acesso SSH

Após o enrollment, SSH não é usado na operação normal. Se não houver necessidade de novos bootstraps, remova a chave pública do Agent e a regra `/etc/sudoers.d/capivara-agent`. Preserve a chave privada do Controller com permissão `600` enquanto ela for necessária para instalar outros Agents.
