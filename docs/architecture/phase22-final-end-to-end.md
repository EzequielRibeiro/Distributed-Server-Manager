# Fase 22 — Testes finais end-to-end

## Objetivo

Fechar a investigação de criação/provisionamento com um gate final de CI que exercita o caminho de infraestrutura desde bootstrap até criação de instância e garante que falhas internas sejam convertidas em respostas HTTP seguras.

## Gate

A entrada única da fase é:

```bash
bash tests/phase22_final_e2e.sh
```

O manifesto `tests/phase22_scenarios.json` mantém a relação explícita entre cenário e teste automatizado.

## Cenários cobertos

- Fresh Controller;
- Fresh Agent;
- Fresh Hybrid;
- Remote Agent;
- instalação offline por pacote;
- instalação por GitHub Release;
- pairing seguro;
- token expirado;
- token reutilizado;
- Region/Datacenter;
- Agent offline;
- Agent sem localização;
- Agent sem portas elegíveis;
- placement por topologia, health, capabilities e portas;
- Customer contract;
- criação DayZ;
- provisionamento DayZ determinístico em CI;
- reinstalação/duplicidade/reconciliação de Agent;
- restart lógico do Controller com reabertura do mesmo banco;
- upgrade remoto de Agent;
- regressão do HTTP boundary da criação de instâncias.

## Regressão crítica

O teste `tests/phase22_customer_dayz_regression_test.py` percorre:

```text
Customer autenticado
  -> contrato DayZ ativo
  -> RuntimeDefinition dayz.stable
  -> requisitos de placement
  -> Agent elegível
  -> bloco UDP contíguo de 10 portas
  -> criação da instância
  -> vínculo do contrato
  -> status provisioning
  -> reserva persistente das portas
  -> progresso do provisionamento
  -> status final offline/pronto para iniciar
  -> reabertura do banco simulando restart do Controller
  -> instância e portas preservadas
```

A execução externa do SteamCMD não é feita na CI: exigiria credencial Steam, download de grande porte e acesso a serviço externo. O boundary externo é substituído por um provisionador determinístico, enquanto o contrato, catálogo, placement, persistência, alocação de portas, estados e progresso usam os componentes reais do Capivara.

## Garantia contra ERR_EMPTY_RESPONSE

`dashboard/instance_creation_http.py` é tratado como boundary obrigatório. O teste injeta deliberadamente `RuntimeError` no serviço de criação e exige:

```text
HTTP 500
error = instance_creation_failed
mensagem pública estável
sem texto interno da exceção
```

Portanto uma exceção de domínio/runtime não pode escapar até `socketserver` e encerrar a conexão sem resposta. O comportamento esperado é sempre uma resposta HTTP serializável.

## Critério de conclusão

A Fase 22 só passa quando:

1. todos os testes unitários/integrados anteriores permanecem verdes;
2. os pacotes Linux/Windows continuam válidos;
3. smoke Linux e updater permanecem verdes;
4. `Phase 22 final end-to-end gate` passa integralmente;
5. o cenário crítico Customer -> DayZ -> Placement -> Portas -> Provision -> Progresso conclui com HTTP 201;
6. a regressão de exceção interna conclui com HTTP 500 seguro, nunca conexão vazia.
