# Fase 7 — Wizard Criar servidor

Status: implementação.

## Objetivo

Corrigir a duplicidade funcional e os estados inconsistentes do fluxo de criação de servidor no painel do customer.

## CTA

O botão `Criar servidor agora` pertence ao card do contrato e serve apenas para abrir o wizard. Enquanto o wizard estiver aberto, os CTAs de abertura ficam ocultos. O único botão que confirma a operação é `create-instance-submit`, exibido como `Criar servidor` na etapa final.

## Placement readiness

O frontend consulta `GET /api/placement/readiness` ao abrir o wizard.

A resposta é deliberadamente customer-safe:

```json
{
  "placement_ready": true,
  "state": "available"
}
```

O endpoint resolve o Controller do customer autenticado e verifica candidatos elegíveis somente naquele Controller. Ele não expõe Agents, motivos internos, topologia ou contagens administrativas.

Quando não há ambiente elegível, o wizard informa:

`Nenhum ambiente está disponível para provisionamento neste momento.`

A submissão é bloqueada enquanto `placement_ready=false`.

## Fallback regional

O resumo de `Fallback regional` é derivado diretamente do estado real do checkbox `runtime-region-fallback` a cada alteração e imediatamente antes da submissão. Marcado corresponde a `Sim`; desmarcado corresponde a `Não`.

## Estados visuais

O contrato visual da Fase 7 usa os seguintes estados:

- `Verificando ambientes...`
- `Ambiente disponível`
- `Nenhum ambiente disponível`
- `Criando servidor...`
- `Provisionando...`
- `Concluído`
- `Falha`

O POST de criação é observado pela camada de UI para transicionar de criação para provisionamento, conclusão ou falha sem expor detalhes internos de placement.

## Modularização

Arquivos principais:

- `dashboard/placement_readiness_http.py`
- `dashboard/server_part10.py`
- `dashboard/web/create-server-wizard.js`
- `dashboard/web/create-server-wizard.css`

Nenhuma funcionalidade da Fase 7 foi adicionada a `dashboard/server.py`.
