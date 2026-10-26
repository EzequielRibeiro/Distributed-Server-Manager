# Capivara DSM 2.0.128

Candidata de release para correção do fluxo de eventos de instalação e atualização de jogos. **Ainda não publicada.**

## Destaques

- Corrige a interpretação de objetos JSON recebidos por `installer/events.sh`, evitando o acréscimo indevido de uma chave de fechamento.
- Corrige o tratamento do payload JSON em `installer/operation_state.sh`, preservando os dados de estado operacional.
- Ajusta o carregamento isolado do módulo de progresso atômico quando a função de instalação ainda não foi registrada.

## Segurança e confiabilidade

- Preserva o estado operacional e os eventos de falha, instalação, atualização e rollback sem exigir reinicialização dos jogos para validar a correção.
- Nenhuma alteração automática de dados de instâncias é autorizada por estas notas.

## Qualidade

- Inclui testes de regressão de payloads JSON e dos tipos de eventos de instalação.
- Testes isolados executados no horizon-server, incluindo persistência real em SQLite temporário.
- CI e workflows de revisão da PR #950 aprovados.

## Publicação

- Release preparada a partir do merge da PR #950.
- A publicação de tags, artefatos e o deploy exigem aprovação e validações específicas.
