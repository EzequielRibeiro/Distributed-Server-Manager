# Administração de usuários do sistema

A área de usuários do sistema é uma superfície de segurança de alto privilégio e pertence exclusivamente ao papel `admin`.

## Regras obrigatórias

- Somente `admin` pode abrir a página, listar contas, criar, editar, desativar ou excluir usuários do sistema.
- Controller e Operator não recebem acesso administrativo a essa superfície, mesmo que conheçam a URL.
- O sistema nunca pode ficar sem uma conta Admin cadastrada.
- O sistema nunca pode ficar sem pelo menos um Admin ativo.
- O último Admin cadastrado não pode ser excluído nem perder o papel Admin.
- O único Admin ativo não pode ser excluído ou desativado, mesmo quando exista outro Admin desativado.
- O administrador conectado não pode excluir, desativar ou rebaixar a própria conta.
- As mesmas invariantes devem existir no backend; o estado do botão da interface é apenas uma camada adicional de prevenção.

## Senha inicial

A criação de uma conta não solicita uma senha escolhida pelo administrador.

Fluxo:

1. Admin informa os dados da conta.
2. Capivara gera uma senha aleatória de alta entropia.
3. Somente o hash da senha é persistido.
4. A senha temporária é mostrada uma única vez ao Admin para entrega ao usuário.
5. No primeiro acesso, a conta fica limitada à tela de troca de senha.
6. Após definir uma nova senha, o marcador de senha temporária desaparece e a sessão passa a usar a nova credencial.

O administrador não deve conhecer a senha permanente de outro usuário.

## Dados funcionais do cadastro

O modelo definitivo da conta do sistema deve separar autenticação de informações funcionais. Além de `username`, `role`, vínculo e `active`, o baseline do banco deve incluir:

- `full_name` — nome completo, obrigatório;
- `email` — e-mail corporativo, obrigatório e único quando informado;
- `phone` — telefone de contato, opcional;
- `job_title` — cargo ou função, opcional;
- `department` — departamento, equipe ou área, opcional;
- `created_by` — Admin responsável pela criação;
- `last_login_at` — último acesso confirmado;
- `password_changed_at` — última troca de senha;
- `created_at` e `updated_at`.

Campos técnicos continuam separados:

- `role`: `admin`, `controller` ou `operator`;
- `scope_id`: vínculo técnico, aplicável ao papel Controller;
- `active`: habilitação da conta;
- estado da senha: temporária ou definida.

Esses dados funcionais devem ser persistidos no banco canônico. Não usar arquivo JSON paralelo nem codificar metadados dentro de `scope_id`.

## Auditoria

As seguintes ações devem produzir registro de auditoria sem incluir senha ou hash:

- criação de usuário;
- edição de papel/vínculo;
- ativação/desativação;
- geração ou redefinição de senha temporária;
- troca da senha temporária pelo próprio usuário;
- tentativa bloqueada de excluir/rebaixar o último Admin;
- exclusão de conta.
