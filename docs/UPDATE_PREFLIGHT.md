# Update preflight read-only

O Capivara DSM possui um gate de readiness que deve ser executado **antes** da janela de manutenção:

```bash
sudo cap update preflight
```

O comando consulta a release estável mais recente, baixa o pacote DSM e o SHA256 oficial para um diretório temporário fora de `/opt/dsm`, valida checksum e estrutura do arquivo e, somente depois, executa o contrato de preflight fornecido pela própria release alvo.

## O que o preflight valida

- a instalação atual possui versão SemVer válida;
- existe uma versão estável mais nova;
- pacote e checksum oficiais da release estão disponíveis;
- o pacote corresponde à versão anunciada pela tag;
- o pacote alvo contém os componentes obrigatórios de update;
- usuário, grupo e home do runtime DSM são válidos;
- as árvores protegidas (`instances`, `game-data` e estado Hybrid) podem ser preservadas atomicamente;
- não há resíduos de uma atualização/rollback incompletos;
- existe espaço suficiente para a transação de update;
- o banco atual é compatível com o pacote alvo, usando o `process-guard.sh` da própria versão alvo;
- nenhuma instância de jogo está ativa.

## Garantia de somente leitura

O preflight **não**:

- para ou reinicia serviços;
- encerra instâncias de jogo;
- executa migrações;
- cria backup;
- grava no cache de update dentro de `/opt/dsm`;
- substitui arquivos de `/opt/dsm`;
- altera unidades systemd;
- registra o update como concluído.

Downloads e extração existem apenas em um workspace temporário e são removidos ao final.

## Interpretação do resultado

Sucesso termina com:

```text
UPDATE PREFLIGHT VERIFIED: release=X.Y.Z instalada=A.B.C; nenhuma alteração foi aplicada.
```

Se a instalação já estiver na release estável mais recente, o comando termina com sucesso informando que o preflight não é necessário.

Qualquer `PRECHECK FAIL` deve bloquear a abertura da janela de manutenção. Corrija a causa e execute novamente o preflight antes de `cap update run`.

## Sequência operacional recomendada

```bash
cap update check
sudo cap update preflight
sudo cap update run
cap update check
cap operations readiness
```

O `preflight` reduz risco antes do update, mas não substitui as validações transacionais do `update.sh`. O updater continua reexecutando o Process Guard imediatamente antes da mutação para impedir uma corrida em que uma instância seja iniciada entre o preflight e o update real.
