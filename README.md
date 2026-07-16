# Hub Imob

O **Hub Imob** é uma plataforma que reúne anúncios de imóveis de diferentes imobiliárias em um único lugar.

O objetivo do projeto é permitir que uma pessoa pesquise imóveis por cidade, preço, número de quartos e outros filtros, visualize os anúncios disponíveis e seja redirecionada para o site original da imobiliária responsável pelo imóvel.

---

# 1. Tecnologias utilizadas

O projeto está dividido em diferentes partes:

* **Frontend:** Next.js
* **Backend:** FastAPI
* **Banco de dados:** PostgreSQL hospedado no Supabase
* **ORM:** SQLAlchemy
* **Migrations:** Alembic
* **Web scraping:** Python
* **Versionamento:** Git e GitHub

Não é necessário entender todas essas tecnologias para rodar o projeto. Este documento apresenta os comandos necessários passo a passo.

---

# 2. Estrutura do projeto

A estrutura pode ser semelhante a esta:

```text
hub_imob/
├── backend/
│   ├── app/
│   ├── alembic/
│   ├── requirements.txt
│   └── .env
│
├── frontend/
│   ├── pages/
│   ├── components/
│   ├── package.json
│   └── .env.local
│
├── scrapers/
├── infra/
├── .gitignore
└── README.md
```

As principais pastas são:

| Pasta      | Função                                    |
| ---------- | ----------------------------------------- |
| `backend`  | API, banco de dados e regras de negócio   |
| `frontend` | Interface visual do site                  |
| `scrapers` | Código responsável por coletar imóveis    |
| `infra`    | Arquivos relacionados à infraestrutura    |
| `alembic`  | Histórico de alterações do banco de dados |

---

# 3. Programas necessários

Antes de começar, instale os seguintes programas.

## 3.1 Git

O Git é usado para baixar o projeto e controlar as alterações no código.

No Ubuntu ou Debian:

```bash
sudo apt update
sudo apt install git
```

Verifique a instalação:

```bash
git --version
```

---

## 3.2 Python

O backend utiliza Python.

Instale o Python, o gerenciador de pacotes e o suporte a ambientes virtuais:

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

Verifique:

```bash
python3 --version
```

---

## 3.3 Node.js e npm

O frontend utiliza Node.js e npm.

Uma forma recomendada de instalar é usando o NVM.

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
```

Feche e abra novamente o terminal.

Depois, instale uma versão estável do Node.js:

```bash
nvm install --lts
nvm use --lts
```

Verifique:

```bash
node --version
npm --version
```

---

## 3.4 Visual Studio Code

O Visual Studio Code é o editor recomendado para abrir e alterar o projeto.

Depois de instalado, é possível abrir a pasta atual usando:

```bash
code .
```

---

# 4. Configurar o Git pela primeira vez

Caso você nunca tenha utilizado Git neste computador, configure seu nome e e-mail.

```bash
git config --global user.name "Seu Nome"
git config --global user.email "seu-email@example.com"
```

Exemplo:

```bash
git config --global user.name "Caio Penayo"
git config --global user.email "email-usado-no-github@example.com"
```

Verifique a configuração:

```bash
git config --global --list
```

---

# 5. Clonar o repositório

Clonar significa baixar uma cópia do projeto do GitHub para o seu computador.

Escolha uma pasta onde deseja salvar o projeto.

Exemplo:

```bash
cd ~/Desktop
```

Clone o repositório:

```bash
git clone https://github.com/caiopenayo/hub_imob.git
```

Entre na pasta:

```bash
cd hub_imob
```

Confirme que está na pasta correta:

```bash
pwd
```

Liste os arquivos:

```bash
ls
```

---

# 6. Abrir o projeto no Visual Studio Code

Dentro da pasta do projeto, execute:

```bash
code .
```

Caso o comando `code` não funcione, abra o Visual Studio Code manualmente e selecione:

```text
File → Open Folder
```

Depois, escolha a pasta `hub_imob`.

---

# 7. Atualizar o projeto

Antes de começar qualquer alteração, atualize sua cópia local.

Entre na branch principal:

```bash
git switch main
```

Baixe as alterações mais recentes:

```bash
git pull origin main
```

Isso reduz o risco de trabalhar sobre uma versão antiga do projeto.

---

# 8. Criar uma nova branch

Uma branch é uma área separada para realizar alterações sem modificar diretamente a versão principal do projeto.

Nunca faça alterações importantes diretamente na branch `main`.

Primeiro, confirme que está na branch `main`:

```bash
git switch main
```

Atualize o projeto:

```bash
git pull origin main
```

Crie uma nova branch:

```bash
git switch -c nome-da-branch
```

Exemplo:

```bash
git switch -c feature-filtros-de-busca
```

Outros exemplos de nomes:

```text
feature-login
feature-favoritos
fix-erro-preco
fix-paginacao
refactor-property-card
docs-atualizar-readme
```

Uma boa prática é usar nomes sem espaços, sem acentos e com letras minúsculas.

---

# 9. Ver em qual branch você está

Execute:

```bash
git branch
```

A branch atual aparecerá com um asterisco:

```text
  main
* feature-filtros-de-busca
```

Também é possível executar:

```bash
git status
```

---

# 10. Trocar de branch

Para entrar em uma branch existente:

```bash
git switch nome-da-branch
```

Exemplo:

```bash
git switch main
```

Ou:

```bash
git switch feature-filtros-de-busca
```

Para listar todas as branches locais:

```bash
git branch
```

Para listar branches locais e remotas:

```bash
git branch -a
```

---

# 11. Configurar o backend

Entre na pasta do backend:

```bash
cd backend
```

---

## 11.1 Criar um ambiente virtual

O ambiente virtual mantém as dependências Python do projeto isoladas das demais dependências do computador.

Crie o ambiente:

```bash
python3 -m venv .venv
```

Ative o ambiente:

```bash
source .venv/bin/activate
```

Quando o ambiente estiver ativo, o terminal mostrará algo semelhante a:

```text
(.venv) usuario@computador:~/Desktop/hub_imob/backend$
```

Sempre que abrir um novo terminal para trabalhar no backend, será necessário ativar novamente:

```bash
cd ~/Desktop/hub_imob/backend
source .venv/bin/activate
```

Para desativar:

```bash
deactivate
```

---

## 11.2 Instalar dependências do backend

Com o ambiente virtual ativo:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

O arquivo `requirements.txt` contém a lista de bibliotecas utilizadas pelo backend.

---

# 12. Configurar as variáveis de ambiente do backend

O projeto utiliza variáveis de ambiente para armazenar informações como:

* endereço do banco de dados;
* configurações do Supabase;
* chaves privadas;
* URLs internas;
* ambiente de execução.

Essas informações normalmente ficam em um arquivo chamado `.env`.

Entre na pasta do backend:

```bash
cd backend
```

Caso exista um arquivo `.env.example`, copie-o:

```bash
cp .env.example .env
```

Depois, abra o arquivo:

```bash
code .env
```

Um exemplo de conteúdo pode ser:

```env
DATABASE_URL=postgresql+asyncpg://USUARIO:SENHA@HOST:5432/postgres

SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sua-chave-do-supabase

ENVIRONMENT=development
```

Os valores reais devem ser fornecidos pelo responsável pelo projeto.

Nunca envie o arquivo `.env` para o GitHub.

O `.gitignore` deve conter:

```text
.env
.venv
__pycache__
```

---

# 13. Configurar o banco de dados

O projeto utiliza Alembic para criar e atualizar as tabelas do banco.

Com o ambiente virtual ativo e dentro da pasta `backend`, execute:

```bash
alembic upgrade head
```

Esse comando executa todas as migrations pendentes.

Para verificar a migration atual:

```bash
alembic current
```

Para visualizar o histórico:

```bash
alembic history
```

Não crie ou edite migrations sem entender o impacto no banco de dados.

---

# 14. Rodar o backend

Com o ambiente virtual ativo e dentro da pasta `backend`, execute:

```bash
uvicorn app.main:app --reload
```

Dependendo da estrutura do projeto, o comando também pode ser:

```bash
uvicorn main:app --reload
```

O terminal mostrará algo semelhante a:

```text
Uvicorn running on http://127.0.0.1:8000
```

Abra no navegador:

```text
http://localhost:8000
```

Documentação interativa da API:

```text
http://localhost:8000/docs
```

Documentação alternativa:

```text
http://localhost:8000/redoc
```

Endpoint de verificação:

```text
http://localhost:8000/health
```

Para parar o backend, pressione:

```text
Ctrl + C
```

---

# 15. Configurar o frontend

Abra um segundo terminal.

Entre na pasta do frontend:

```bash
cd ~/Desktop/hub_imob/frontend
```

Instale as dependências:

```bash
npm install
```

Esse comando lê o arquivo `package.json` e instala as bibliotecas necessárias.

---

# 16. Configurar as variáveis de ambiente do frontend

Caso exista um arquivo `.env.example` ou `.env.local.example`, copie-o:

```bash
cp .env.local.example .env.local
```

Abra o arquivo:

```bash
code .env.local
```

Exemplo:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

A variável `NEXT_PUBLIC_API_URL` informa ao frontend onde o backend está rodando.

Nunca coloque senhas ou chaves privadas em variáveis que começam com:

```text
NEXT_PUBLIC_
```

Essas variáveis podem ficar visíveis no navegador.

---

# 17. Rodar o frontend

Dentro da pasta `frontend`, execute:

```bash
npm run dev
```

O terminal deverá mostrar algo semelhante a:

```text
Local: http://localhost:3000
```

Abra no navegador:

```text
http://localhost:3000
```

Para parar o frontend:

```text
Ctrl + C
```

---

# 18. Rodar frontend e backend ao mesmo tempo

Normalmente, são necessários dois terminais.

## Terminal 1 — Backend

```bash
cd ~/Desktop/hub_imob/backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

## Terminal 2 — Frontend

```bash
cd ~/Desktop/hub_imob/frontend
npm run dev
```

Depois, abra:

```text
http://localhost:3000
```

O frontend acessará o backend em:

```text
http://localhost:8000
```

---

# 19. Verificar alterações realizadas

Depois de modificar arquivos, execute na pasta principal do projeto:

```bash
cd ~/Desktop/hub_imob
git status
```

Arquivos modificados aparecerão em vermelho.

Exemplo:

```text
modified: frontend/pages/index.tsx
modified: backend/app/main.py
```

Para visualizar exatamente o que mudou:

```bash
git diff
```

---

# 20. Preparar alterações para um commit

Adicione todos os arquivos modificados:

```bash
git add .
```

Ou adicione apenas um arquivo específico:

```bash
git add frontend/pages/index.tsx
```

Verifique novamente:

```bash
git status
```

Os arquivos preparados para o commit aparecerão em verde.

---

# 21. Criar um commit

Um commit registra um conjunto de alterações no histórico do projeto.

Execute:

```bash
git commit -m "Descrição da alteração"
```

Exemplo:

```bash
git commit -m "Adiciona filtro por número de quartos"
```

Outros exemplos:

```bash
git commit -m "Corrige paginação dos imóveis"
git commit -m "Melhora layout dos filtros"
git commit -m "Adiciona endpoint de favoritos"
git commit -m "Atualiza documentação do projeto"
```

Use uma mensagem curta, mas clara.

---

# 22. Enviar a branch para o GitHub

Na primeira vez que enviar uma nova branch:

```bash
git push -u origin nome-da-branch
```

Exemplo:

```bash
git push -u origin feature-filtros-de-busca
```

Depois disso, os próximos envios podem ser feitos apenas com:

```bash
git push
```

---

# 23. Criar um Pull Request

Depois de enviar a branch para o GitHub:

1. Abra o repositório no GitHub.
2. Acesse:

```text
https://github.com/caiopenayo/hub_imob
```

3. O GitHub normalmente mostrará o botão:

```text
Compare & pull request
```

4. Clique no botão.
5. Escreva um título claro.
6. Descreva o que foi alterado.
7. Clique em:

```text
Create pull request
```

Exemplo de título:

```text
Adiciona filtro por número de quartos
```

Exemplo de descrição:

```text
Esta alteração adiciona um filtro de número mínimo de quartos na página de busca.

Alterações realizadas:

- adicionado campo no frontend;
- parâmetro enviado para a API;
- filtro aplicado no backend;
- estado vazio atualizado.
```

O Pull Request permite revisar as alterações antes de incorporá-las à branch principal.

---

# 24. Atualizar sua branch com as alterações da main

Enquanto você trabalha, outras pessoas podem alterar a branch `main`.

Para atualizar sua branch:

```bash
git switch main
git pull origin main
git switch nome-da-sua-branch
git merge main
```

Exemplo:

```bash
git switch main
git pull origin main
git switch feature-filtros-de-busca
git merge main
```

Caso não existam conflitos, o Git fará a atualização automaticamente.

---

# 25. Conflitos de Git

Um conflito acontece quando duas pessoas alteram a mesma parte de um arquivo.

O Git mostrará algo semelhante a:

```text
CONFLICT (content): Merge conflict in frontend/pages/index.tsx
```

Dentro do arquivo, aparecerá:

```text
<<<<<<< HEAD
Código da sua branch
=======
Código vindo da outra branch
>>>>>>> main
```

Você deve escolher qual código manter e apagar os marcadores:

```text
<<<<<<< HEAD
=======
>>>>>>> main
```

Depois:

```bash
git add .
git commit -m "Resolve conflito com a main"
git push
```

Não resolva conflitos sem entender qual versão deve permanecer.

---

# 26. Descartar alterações locais

Para descartar alterações de um arquivo ainda não adicionado:

```bash
git restore caminho-do-arquivo
```

Exemplo:

```bash
git restore frontend/pages/index.tsx
```

Para descartar todas as alterações não adicionadas:

```bash
git restore .
```

Atenção: esse comando remove as alterações locais.

---

# 27. Remover arquivos da área de commit

Caso tenha executado `git add .` por engano:

```bash
git restore --staged .
```

Para remover apenas um arquivo da área de commit:

```bash
git restore --staged caminho-do-arquivo
```

As alterações continuam no computador, mas deixam de estar preparadas para o commit.

---

# 28. Apagar uma branch local

Primeiro, saia da branch que deseja apagar:

```bash
git switch main
```

Depois:

```bash
git branch -d nome-da-branch
```

Exemplo:

```bash
git branch -d feature-filtros-de-busca
```

Caso a branch ainda não tenha sido incorporada:

```bash
git branch -D nome-da-branch
```

Use `-D` com cuidado.

---

# 29. Apagar uma branch remota

Para apagar a branch do GitHub:

```bash
git push origin --delete nome-da-branch
```

Exemplo:

```bash
git push origin --delete feature-filtros-de-busca
```

Normalmente, o GitHub também permite apagar a branch depois que o Pull Request é aprovado.

---

# 30. Rodar os scrapers

A forma exata depende da estrutura do projeto.

Um exemplo possível:

```bash
cd ~/Desktop/hub_imob/backend
source .venv/bin/activate
python -m app.scrapers.run
```

Outro exemplo:

```bash
python scripts/run_scrapers.py
```

Também pode existir um endpoint no backend, como:

```text
POST /scrape
```

A documentação disponível em:

```text
http://localhost:8000/docs
```

deve indicar os endpoints disponíveis.

Antes de rodar um scraper, verifique:

* se o backend está configurado;
* se o banco está acessível;
* se as variáveis de ambiente estão preenchidas;
* se o scraper pertence a uma fonte válida;
* se o site permite o tipo de acesso realizado.

---

# 31. Comandos mais utilizados

## Git

```bash
git status
git branch
git branch -a
git switch main
git switch nome-da-branch
git switch -c nova-branch
git add .
git commit -m "Descrição"
git push
git pull
git diff
```

## Backend

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

---

# 32. Fluxo recomendado para fazer uma alteração

Sempre siga este fluxo:

```bash
git switch main
git pull origin main
git switch -c nome-da-nova-branch
```

Faça as alterações.

Depois:

```bash
git status
git add .
git commit -m "Descrição da alteração"
git push -u origin nome-da-nova-branch
```

Por fim, crie um Pull Request no GitHub.

Exemplo completo:

```bash
git switch main
git pull origin main
git switch -c feature-favoritos

# Faça as alterações nos arquivos.

git status
git add .
git commit -m "Adiciona sistema de favoritos"
git push -u origin feature-favoritos
```

---

# 33. Erros comuns

## Erro: `src refspec main does not match any`

Esse erro normalmente acontece quando ainda não existe nenhum commit local.

Solução:

```bash
git add .
git commit -m "Initial commit"
git branch -M main
git push -u origin main
```

---

## Erro: `remote origin already exists`

O repositório remoto já foi configurado.

Verifique:

```bash
git remote -v
```

Para alterar:

```bash
git remote set-url origin https://github.com/caiopenayo/hub_imob.git
```

---

## Erro: `ModuleNotFoundError`

Normalmente significa que as dependências Python não foram instaladas ou o ambiente virtual não está ativo.

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Erro: `uvicorn: command not found`

Ative o ambiente virtual e instale as dependências:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Também é possível executar:

```bash
python -m uvicorn app.main:app --reload
```

---

## Erro: `npm: command not found`

O Node.js ou npm não está instalado.

Instale usando o NVM e tente novamente.

---

## Erro: porta 3000 já está sendo utilizada

Encerre o processo anterior ou rode em outra porta:

```bash
npm run dev -- -p 3001
```

Acesse:

```text
http://localhost:3001
```

---

## Erro: porta 8000 já está sendo utilizada

Rode o backend em outra porta:

```bash
uvicorn app.main:app --reload --port 8001
```

Nesse caso, atualize o frontend:

```env
NEXT_PUBLIC_API_URL=http://localhost:8001
```

Reinicie o frontend depois de alterar o `.env.local`.

---

## Erro de conexão com o banco de dados

Verifique:

* se `DATABASE_URL` está preenchida;
* se a senha está correta;
* se o projeto Supabase está ativo;
* se a internet está funcionando;
* se o endereço utiliza o driver esperado;
* se as migrations foram executadas.

Execute:

```bash
alembic upgrade head
```

---

## Alterei o `.env`, mas nada mudou

Reinicie o processo.

Backend:

```text
Ctrl + C
```

Depois:

```bash
uvicorn app.main:app --reload
```

Frontend:

```text
Ctrl + C
```

Depois:

```bash
npm run dev
```

---

# 34. Arquivos que não devem ser enviados ao GitHub

O arquivo `.gitignore` deve impedir o envio de arquivos privados ou gerados automaticamente.

Exemplo:

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
venv/

# Variáveis de ambiente
.env
.env.*
!.env.example

# Node
node_modules/
.next/
out/

# Logs
*.log

# Sistema operacional
.DS_Store

# Editor
.vscode/
.idea/

# Testes e cobertura
.pytest_cache/
.coverage
htmlcov/

# Arquivos temporários
tmp/
temp/
```

Nunca envie:

* senhas;
* tokens;
* chaves do Supabase;
* URLs privadas com credenciais;
* arquivos `.env`;
* dados pessoais;
* arquivos grandes desnecessários.

---

# 35. Boas práticas

* Não altere diretamente a branch `main`.
* Crie uma branch para cada funcionalidade ou correção.
* Faça commits pequenos e claros.
* Atualize sua branch antes de começar.
* Teste frontend e backend antes de criar o Pull Request.
* Não envie arquivos `.env`.
* Não envie senhas ou tokens.
* Leia as alterações com `git diff`.
* Execute `git status` antes de cada commit.
* Explique no Pull Request o que foi alterado.
* Não rode scrapers agressivamente sem avaliar o impacto.

---

# 36. Checklist antes de criar um Pull Request

Antes de enviar suas alterações, verifique:

* [ ] Estou na branch correta.
* [ ] Minha branch foi criada a partir da `main` atualizada.
* [ ] O backend inicia sem erros.
* [ ] O frontend inicia sem erros.
* [ ] A funcionalidade foi testada.
* [ ] Não incluí senhas ou arquivos `.env`.
* [ ] Revisei as alterações com `git diff`.
* [ ] Os nomes das variáveis e arquivos estão claros.
* [ ] O commit possui uma mensagem descritiva.
* [ ] O Pull Request explica o que foi feito.

---

# 37. Primeira execução resumida

Para uma pessoa que acabou de baixar o projeto:

## Baixar o projeto

```bash
cd ~/Desktop
git clone https://github.com/caiopenayo/hub_imob.git
cd hub_imob
```

## Configurar o backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

## Configurar o frontend

Abra outro terminal:

```bash
cd ~/Desktop/hub_imob/frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Abra:

```text
http://localhost:3000
```

---

# 38. Fluxo resumido para contribuir

```bash
git switch main
git pull origin main
git switch -c nome-da-branch

# Faça as alterações.

git add .
git commit -m "Descrição da alteração"
git push -u origin nome-da-branch
```

Depois, crie um Pull Request no GitHub.

---

# 39. Suporte

Caso encontre um problema:

1. Copie a mensagem completa de erro.
2. Informe qual comando foi executado.
3. Informe em qual pasta o comando foi executado.
4. Execute:

```bash
git status
```

5. Para erros no backend, informe também:

```bash
python3 --version
pip --version
```

6. Para erros no frontend, informe:

```bash
node --version
npm --version
```

7. Não envie senhas, tokens ou o conteúdo completo do arquivo `.env`.

---

# 40. Licença

Defina aqui a licença do projeto.

Exemplo:

```text
Este projeto é privado e não pode ser copiado, distribuído ou utilizado sem autorização.
```

Ou utilize uma licença como MIT, Apache 2.0 ou GPL, caso o projeto seja público.
