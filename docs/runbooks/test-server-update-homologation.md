# Homologação completa do Update Manager em servidor de testes

Este procedimento valida A5–A8 contra um `systemd` real e deve ser executado
somente em um servidor DSM descartável ou dedicado a testes. O teste realiza
duas reinstalações da versão informada, incluindo um rollback intencional.

## Pré-condições

- Linux com `systemd` ativo e acesso `root`.
- DSM instalado em `/opt/dsm` e operacional.
- Backup externo ou snapshot da VM criado antes da execução.
- Release extraída em um diretório fora de `/opt/dsm`.
- A versão do pacote deve ser a mesma da instalação. O teste usa
  `--allow-same-version` para homologar o updater sem trocar de release.
- `curl`, `python3`, `sha256sum` e `systemctl` disponíveis.
- Nenhuma atualização DSM concorrente.

Não execute em produção. Durante o teste os serviços DSM são reiniciados e um
segundo update falha propositalmente para provar o rollback.

## Execução

No checkout correspondente exatamente à release que será testada:

```bash
sudo env DSM_HOMOLOGATION_CONFIRM=dedicated-test-server \
  bash tests/test_server_update_homologation.sh \
  /srv/releases/capivara-dsm-X.Y.Z
```

Para guardar as evidências em outro volume:

```bash
sudo env \
  DSM_HOMOLOGATION_CONFIRM=dedicated-test-server \
  DSM_HOMOLOGATION_EVIDENCE_ROOT=/mnt/evidence/dsm \
  bash tests/test_server_update_homologation.sh \
  /srv/releases/capivara-dsm-X.Y.Z
```

## Cobertura e critérios de aprovação

1. O ambiente, versão, unidades DSM e saúde inicial são registrados.
2. Quatro unidades descartáveis reproduzem `active+enabled`,
   `activating+enabled`, `failed+enabled` e `active+disabled`.
3. Uma reinstalação real deve restaurar as três unidades habilitadas e deixar a
   unidade desabilitada parada e desabilitada.
4. O gate deve aprovar systemd, `cap`, banco configurado e `/health` quando o
   Dashboard estiver ativo.
5. Uma unidade adicional falha somente no restart pós-update. O updater deve
   retornar erro, coletar diagnóstico e executar rollback.
6. Após o rollback, versão, configuração, banco, CLI e serviços devem estar
   saudáveis; a unidade causadora da falha deve voltar a `active`.
7. `result.env` deve terminar com `status=passed`.

As evidências ficam em
`/var/tmp/dsm-update-homologation/<timestamp-pid>/` por padrão. Preserve o
diretório completo junto com o snapshot e a identificação da release.

## Evidências produzidas

- inventário do host e das unidades antes/depois;
- saída do `cap --help`;
- resultado JSON do health check do banco;
- resposta `/health` do Dashboard, quando aplicável;
- log integral do update bem-sucedido;
- log integral da falha e rollback controlados;
- diretório de diagnóstico externo à instalação, sob o `BACKUP_DIR` configurado;
- `result.env` com versão, identificador e resultado final.

## Recuperação se o teste for interrompido

O trap remove apenas as unidades temporárias cujo nome contém o identificador
único da execução. Se o processo for morto sem permitir o cleanup, localize o
`test_id` no diretório de evidências e execute:

```bash
sudo systemctl disable --now 'dsm-homologation-<test_id>-*.service'
sudo rm -f /etc/systemd/system/dsm-homologation-<test_id>-*.service
sudo systemctl daemon-reload
```

Depois confirme a saúde normal com:

```bash
sudo systemctl --failed
sudo /opt/dsm/bin/cap --help
sudo python3 /opt/dsm/database/manager.py --root /opt/dsm check
curl --fail http://127.0.0.1:8080/health
```
