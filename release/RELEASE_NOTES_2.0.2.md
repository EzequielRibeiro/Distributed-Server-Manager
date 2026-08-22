# Capivara DSM 2.0.2

Release corretiva para instalação e inicialização do Agent Linux.

## Correções

- instala todos os módulos Python incluídos no pacote do Agent Linux;
- corrige `ModuleNotFoundError: No module named 'backup_client'`;
- inclui os clientes de observabilidade, configuração, conteúdo, backup e broadcast;
- reforça o teste do pacote para garantir que cada módulo empacotado também seja copiado pelo instalador;
- mantém a recuperação do Update Manager quando `log_info` não foi carregado.
