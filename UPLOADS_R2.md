# Por que as imagens sumiam e como isso foi corrigido

O Render (no plano free e também no pago sem disco anexado) tem sistema de
arquivos **efêmero**: qualquer arquivo salvo pelo app em disco (como as
imagens que você envia no painel admin) é apagado sempre que o serviço
reinicia, hiberna por inatividade ou faz um novo deploy. O banco MySQL na
Aiven continua com o *caminho* da imagem salvo certinho — só o *arquivo*
em si que desaparecia.

A correção: o app agora pode enviar as imagens para um bucket do
**Cloudflare R2** (armazenamento de objetos compatível com S3, com camada
gratuita de 10 GB e sem cobrança por saída de dados) em vez do disco local.
Sem isso configurado, ele volta a salvar em disco local — o que funciona
bem para rodar na sua máquina, mas não em produção no Render.

## Passo a passo (leva uns 10 minutos)

### 1. Crie uma conta e um bucket no Cloudflare R2
1. Acesse https://dash.cloudflare.com/ → **R2 Object Storage** (crie uma conta grátis se não tiver).
2. Clique em **Create bucket**, dê um nome (ex: `portfolio-nathan`) e crie.
3. Anote o **Account ID**, mostrado no canto da tela do R2.

### 2. Habilite acesso público ao bucket
1. Dentro do bucket criado, vá em **Settings** → **Public Access**.
2. Ative o **R2.dev subdomain** (gera algo como `https://pub-xxxxxxxx.r2.dev`).
   - Isso é suficiente para um portfólio. Se quiser um domínio próprio
     (ex: `imagens.seudominio.com`), dá pra configurar depois em **Custom Domains**.
3. Guarde essa URL pública — é o valor de `R2_PUBLIC_BASE_URL`.

### 3. Gere as credenciais de API
1. Ainda em R2, vá em **Manage R2 API Tokens** (ou **Account Home** → **R2** → **API tokens**).
2. Crie um token com permissão de **Object Read & Write**, restrito ao bucket criado.
3. Copie o **Access Key ID** e o **Secret Access Key** (só aparecem uma vez).

### 4. Configure as variáveis de ambiente no Render
No painel do seu serviço no Render → **Environment**, adicione:

| Variável | Valor |
|---|---|
| `R2_ACCOUNT_ID` | o Account ID do passo 1 |
| `R2_ACCESS_KEY_ID` | do passo 3 |
| `R2_SECRET_ACCESS_KEY` | do passo 3 |
| `R2_BUCKET_NAME` | nome do bucket (ex: `portfolio-nathan`) |
| `R2_PUBLIC_BASE_URL` | a URL pública do passo 2, **sem barra no final** |

Salve — o Render vai reimplantar o serviço automaticamente.

### 5. Reenvie as imagens já existentes
As imagens enviadas antes dessa mudança já foram perdidas (o arquivo local
sumiu, só o link ficou no banco). Depois do deploy com as variáveis acima,
entre no painel `/admin` e reenvie a capa/imagens de cada projeto e o seu
avatar — a partir daí elas ficam salvas no R2 e não somem mais em restarts
ou deploys.

## E localmente, na sua máquina?

Se você não configurar as variáveis `R2_*` no seu `.env` local, o app volta
a salvar em `static/uploads/` automaticamente — nada muda no seu fluxo de
desenvolvimento.
