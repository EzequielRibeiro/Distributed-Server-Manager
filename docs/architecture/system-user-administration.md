# Administração de usuários do sistema

A área de usuários do sistema é uma superfície de segurança de alto privilégio e pertence exclusivamente ao papel `admin`.

## Regras obrigatórias

- Somente `admin` pode abrir a página, listar contas, criar, editar, desativar ou excluir usuários do sistema.
- Controller e Operator não recebem acesso administrativo a essa superfície, mesmo que conheçam a URL.
- O sistema nunca pode ficar sem uma conta Admin cadastrada.
- O sistema nunca pode ficar sem pelo menos um Admin ativo.
- O último Admin cadastrado não pode ser excluído nem perder o papel Admin.
- O único Admin ativo não pode ser excluído ou desativado, mesmo quando exista outro Admin desativado.
- O administrador conectado não pode excluir, desativar ou rebaixar a própria conta pela interface administrativa.
- As invariantes de Admin existem também na camada transacional de persistência; o estado do botão da interface é apenas uma camada adicional de prevenção.

## Senha inicial

A criação de uma conta não solicita uma senha escolhida pelo administrador.

Fluxo:

1. Admin informa os dados funcionais e técnicos da conta.
2. Capivara gera uma senha aleatória de alta entropia.
3. Somente o hash `scrypt` marcado como temporário é persistido.
4. A senha temporária é mostrada uma única vez ao Admin para entrega ao usuário.
5. No primeiro acesso, páginas e APIs da aplicação ficam bloqueadas, exceto a identidade da sessão e a troca obrigatória de senha.
6. Após definir uma nova senha, o marcador de senha temporária desaparece e a conta passa a operar normalmente.

O administrador não define nem precisa conhecer a senha permanente de outro usuário.

## Dados funcionais persistidos

O Database Baseline v2 persiste os dados funcionais diretamente em `dashboard_users`, sem JSON paralelo:

- `full_name` — nome completo; obrigatório para novas contas criadas pela Dashboard;
- `corporate_email` — e-mail corporativo; obrigatório para novas contas da Dashboard, normalizado para minúsculas e único;
- `phone` — telefone de contato, opcional;
- `job_title` — cargo ou função, opcional;
- `department` — departamento, equipe ou área, opcional;
- `created_by` — Admin responsável pela criação pela Dashboard;
- `created_at` e `updated_at` — timestamps canônicos da conta.

Os campos são nullable no DDL para preservar o bootstrap inicial e ferramentas administrativas que podem criar o primeiro Admin antes de haver uma identidade funcional completa. A superfície `/users.html`, entretanto, exige nome completo e e-mail corporativo ao criar ou editar contas do sistema.

Campos técnicos continuam separados:

- `username` — login técnico e chave da conta;
- `role` — `admin`, `controller` ou `operator` para esta superfície;
- `scope_id` — vínculo técnico, aplicável ao papel Controller;
- `active` — habilitação da conta;
- `password_hash` — hash da senha, podendo carregar o marcador de primeiro acesso.

## Unicidade e consistência

- `username` continua sendo chave primária e único.
- `corporate_email` possui unicidade no baseline.
- A aplicação normaliza o e-mail para minúsculas antes de persistir, garantindo a mesma identidade entre os backends suportados.
- A validação de duplicidade acontece dentro da transação de criação/edição.
- A proteção do último Admin e do último Admin ativo é conferida na transação de persistência.
- PostgreSQL/MySQL/MariaDB bloqueiam as linhas Admin durante a checagem de invariantes para reduzir risco de alterações administrativas concorrentes.

## Separação de Customer

Esta superfície não administra contas Customer. Usuários Customer continuam no modelo próprio de Customer/account membership. `dashboard_users.customer_id` permanece reservado ao vínculo Customer e é `NULL` para Admin, Controller e Operator.

## Próximas extensões de auditoria

Telemetria como `last_login_at`, `password_changed_at` e trilha administrativa detalhada deve ser adicionada como informação operacional/auditável, sem substituir os campos funcionais acima e sem registrar senha ou hash em eventos.
