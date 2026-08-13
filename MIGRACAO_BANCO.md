# Saindo do Aiven: por que e como migrar para o Neon (Postgres)

## Por que trocar

O plano free do Aiven é "grátis para sempre", mas com uma pegadinha: ele
**desliga o banco sozinho depois de um tempo sem atividade contínua**, e pra
ligar de volta você precisa entrar no console da Aiven manualmente. Não tem
"acordar automático" ao receber uma conexão — é isso que causa os erros de
conexão intermitentes e a sensação de que "o banco dorme".

Pra um portfólio com tráfego esporádico (visitas espaçadas, sem uso
constante), isso é o pior cenário possível: o site fica bonito, mas
qualquer visitante pode cair bem na janela em que o banco está desligado
esperando você notar e religar.

## Por que o Neon resolve isso

O [Neon](https://neon.tech) é Postgres "serverless": quando o banco fica
ocioso, o compute realmente desliga (economia de recursos), mas ele
**acorda sozinho automaticamente na primeira conexão** — sem painel, sem
clique manual. O visitante só percebe um probable delay de 1-2s na primeira
requisição depois de um período ocioso, e não um erro.

Resumo comparativo:

| | Aiven (free) | Neon (free) |
|---|---|---|
| Expira? | Não | Não |
| Cartão de crédito? | Não | Não |
| O que acontece ocioso | Desliga e fica desligado | "Dorme" e acorda sozinho na próxima query |
| Como religar | Manual, no painel | Automático |
| Storage grátis | 1 GB | 0.5 GB (suficiente pra esse projeto) |

O código do app já foi preparado para funcionar com qualquer um dos dois
(detecta o banco pelo prefixo da `DATABASE_URL`), então a troca é só de
configuração — nenhum código a mais para mexer.

## Passo a passo

### 1. Crie o banco no Neon
1. Acesse https://neon.tech e crie uma conta grátis (dá pra usar GitHub).
2. Crie um projeto novo — o Neon já cria um banco `neondb` dentro dele.
3. No dashboard do projeto, vá em **Connection Details** / **Connection string**.
4. Copie a connection string. Ela se parece com:
   ```
   postgresql://usuario:senha@ep-xxxx-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

### 2. Atualize a variável no Render
1. No painel do seu serviço no Render → **Environment**.
2. Edite `DATABASE_URL` e cole a connection string do Neon (pode colar com
   ou sem `?sslmode=require` no final — o app cuida disso sozinho).
3. Salve. O Render vai reimplantar o serviço automaticamente.
4. No primeiro boot, o app detecta que é um banco nunca usado e cria as
   tabelas sozinho (mesma lógica de sincronização de schema que já existia
   pro MySQL) — não precisa rodar nenhum comando manual.

### 3. Traga o conteúdo de volta
Como é um portfólio (poucos projetos, uma lista de habilidades, uma
biografia), a forma mais simples e livre de erro é **reentrar esse
conteúdo pelo próprio painel `/admin`** depois do deploy, em vez de tentar
converter um dump SQL do MySQL pro Postgres (os dois têm sintaxes de dump
diferentes o suficiente pra dar dor de cabeça num banco desse tamanho).

Se preferir mesmo assim migrar os dados automaticamente em vez de digitar
de novo, me avise depois que tiver a connection string do Neon em mãos que
eu preparo um script de migração (lê do Aiven, escreve no Neon) — só não
dá pra rodar esse script daqui do sandbox porque não tenho acesso de rede
a bancos externos.

### 4. Depois de confirmar que está tudo certo, cancele/pause o Aiven
Com o site funcionando 100% no Neon, você pode desligar o serviço MySQL na
Aiven (ou só deixar de usar — o plano free não cobra, mas não custa nada
liberar o recurso).

## E se eu quiser continuar com MySQL, só trocando de provedor?

O código também aceita normalmente uma `DATABASE_URL` de MySQL (ex:
PlanetScale, Railway, Clever Cloud) sem nenhuma mudança — só não resolve o
problema de fundo do "desligamento manual", que é uma característica
específica do Aiven, não do MySQL em si. Por isso a recomendação foi trocar
para o Neon.
