# Portfólio — Nathan Moreira Ramos

## O que mudou nesta versão

Em relação ao projeto original, foram corrigidos os seguintes pontos de segurança:

1. **Credenciais fora do código** — usuário/senha do banco e chave secreta do Flask agora vêm de variáveis de ambiente (arquivo `.env`), nunca ficam hardcoded no `app.py`.
2. **Login no painel `/admin`** — todas as rotas `/admin/*` agora exigem autenticação. Sem login, o usuário é redirecionado para `/admin/login`.
3. **Proteção contra XSS armazenado** — o campo `descricao_longa` (renderizado com `| safe`) agora passa por sanitização (`bleach`) antes de ser salvo no banco, removendo `<script>` e outras tags perigosas.
4. **Uploads com nomes únicos** — arquivos enviados recebem um nome gerado com UUID, evitando que um upload sobrescreva outro com o mesmo nome.
5. **Pool de conexões com o MySQL** — em vez de abrir/fechar uma conexão nova a cada requisição.
6. **Debug desligado por padrão** — `app.run(debug=False)` a menos que `FLASK_DEBUG=true` esteja definido explicitamente (use isso só localmente).
7. **Limite de tamanho de upload** (`MAX_CONTENT_LENGTH = 10MB`) para evitar abuso.

## Novidades desta versão (visual)

- **Modo escuro como padrão**: quem visita pela primeira vez já vê o site no tema escuro. O botão de sol/lua no header continua funcionando normalmente para trocar, e a preferência fica salva no navegador (`localStorage`).
- **Modal de e-mail**: clicar no e-mail do rodapé não abre mais direto o Gmail — abre um quadro com opções (Gmail, Outlook, Yahoo Mail, Apple Mail, app padrão do dispositivo, ou copiar o endereço). Fica em `static/js/email-modal.js` e os estilos em `static/style.css`.

## Configuração

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Criar o arquivo `.env`

Copie o exemplo e preencha os valores:

```bash
cp .env.example .env
```

Gere sua `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Gere o hash da senha do admin (troque `'minhasenha'` pela senha que você quer usar):

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('minhasenha'))"
```

Cole os dois valores no `.env`, junto com as credenciais do seu banco MySQL.

### 3. Rodar

```bash
python app.py
```

Acesse:
- Site: `http://localhost:5000/`
- Painel admin: `http://localhost:5000/admin` (vai pedir login em `/admin/login`)

## Importante antes de publicar

- **Nunca** suba o arquivo `.env` para o GitHub — ele já está no `.gitignore`.
- Em produção, rode com um servidor WSGI de verdade (ex: `gunicorn`), não com `app.run()`.
- Troque a senha padrão de exemplo antes de publicar o site.
- Considere adicionar HTTPS (via proxy reverso, ex: Nginx + Let's Encrypt) se for hospedar publicamente.
