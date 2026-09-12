# Urbe

Plataforma web para emissão e negociação de **cotas de visualização** de filmes.

Cada cota representa **1 visualização única**. Ao transferir a cota para outro proprietário:

- o token antigo é revogado,
- um novo token é emitido para o novo dono,
- somente o token ativo permite liberar o player.

A reprodução é integrada à Bunny.net por URL de embed (assinada em produção via `BUNNY_STREAM_EMBED_TOKEN_KEY`).
O pagamento de lançamento é **Pix via OpenPix**.

## Stack

- Python 3.9+ (stdlib HTTP + `psycopg` quando há Postgres)
- API HTTP + frontend estático em `public/`
- Persistência: JSON local em desenvolvimento, Postgres em produção (`DATABASE_URL`)
- Bunny Stream via API REST
- Pagamentos: `mock` (só desenvolvimento) ou `openpix`

## Setup local

```bash
cp .env.example .env
python3 -m pip install -r requirements.txt
python3 -m py_backend.server
```

Aplicação: `http://localhost:3000`

O arquivo `.env` é lido automaticamente. Variáveis já exportadas no ambiente têm prioridade.

## Testes

```bash
python3 -m unittest discover -s py_backend -p "test_*.py"
```

Os testes cobrem os cenários críticos:

- revogação do token antigo após revenda
- consumo único do token
- falha no player Bunny sem gastar o token
- checkout primário e de revenda
- webhook OpenPix (`OPENPIX:CHARGE_COMPLETED`) e expiração da cobrança
- recusa de valor divergente

## Checklist de lançamento

Antes do `fly deploy`, configure os segredos e rode:

```bash
URBE_ENV=production python3 -m py_backend.server --check
```

O processo só sobe em produção se isto estiver preenchido:

- `DATABASE_URL`
- `PAYMENTS_PROVIDER=openpix` (não use `mock`)
- `OPENPIX_APP_ID`
- `OPENPIX_WEBHOOK_SECRET`
- `BUNNY_STREAM_API_KEY`
- `BUNNY_STREAM_LIBRARY_ID`
- `BUNNY_STREAM_EMBED_TOKEN_KEY`
- `PUBLIC_APP_ORIGIN`

Na OpenPix, cadastre o webhook:

- URL: `https://seu-dominio/api/payments/webhook/openpix`
- eventos: `OPENPIX:CHARGE_COMPLETED` e `OPENPIX:CHARGE_EXPIRED`
- autorização HMAC com o mesmo valor de `OPENPIX_WEBHOOK_SECRET`

Em produção, publicação de filmes fica restrita a produtores (`URBE_OPEN_PUBLISH=0`).
Libere o estúdio com `URBE_PRODUCER_EMAILS` e/ou `URBE_PRODUCER_INVITE`.

## Deploy no Fly.io

Arquivos prontos:

- `Dockerfile`
- `fly.toml` (região `gru`, HTTPS, health check em `/api/health`, 1 máquina sempre ligada para o webhook Pix)

```bash
fly apps create urbe-app
fly postgres create --name urbe-db --region gru
fly postgres attach urbe-db -a urbe-app
fly secrets set \
  OPENPIX_APP_ID=... \
  OPENPIX_WEBHOOK_SECRET=... \
  BUNNY_STREAM_API_KEY=... \
  BUNNY_STREAM_LIBRARY_ID=... \
  BUNNY_STREAM_EMBED_TOKEN_KEY=... \
  URBE_PRODUCER_EMAILS=voce@estudio.com \
  PUBLIC_APP_ORIGIN=https://urbe-app.fly.dev
fly deploy
```

Ajuste `PUBLIC_APP_ORIGIN` e as URLs de checkout em `fly.toml` quando o domínio definitivo estiver no ar.

## Variáveis de ambiente

| Variável | Função |
| --- | --- |
| `PORT` | Porta do servidor |
| `URBE_ENV` | `development` ou `production` |
| `DB_FILE` | Arquivo JSON local (só sem `DATABASE_URL`) |
| `DATABASE_URL` | Postgres em produção |
| `SESSION_DURATION_DAYS` | Duração da sessão |
| `CHECKOUT_RESERVATION_MINUTES` | Reserva da cota/anúncio durante checkout |
| `PLAYBACK_SESSION_SECONDS` | Validade do link `/watch/...` |
| `BUNNY_STREAM_API_KEY` | API Bunny |
| `BUNNY_STREAM_LIBRARY_ID` | Biblioteca padrão |
| `BUNNY_STREAM_EMBED_TOKEN_KEY` | Assinatura do embed |
| `BUNNY_IFRAME_HOST` | Host do iframe (padrão `https://iframe.mediadelivery.net`) |
| `PAYMENTS_PROVIDER` | `mock` ou `openpix` |
| `PAYMENTS_CURRENCY` | Moeda (ex: `BRL`) |
| `PAYMENTS_CHECKOUT_SUCCESS_URL` | Retorno do checkout (`{ORDER_ID}`, `{CHECKOUT_SESSION_ID}`) |
| `PAYMENTS_CHECKOUT_CANCEL_URL` | Cancelamento do checkout |
| `OPENPIX_APP_ID` | App ID da OpenPix (header `Authorization`) |
| `OPENPIX_WEBHOOK_SECRET` | Segredo HMAC do webhook |
| `OPENPIX_SPLIT_PIX_KEY` | Chave Pix da plataforma no split |
| `OPENPIX_SPLIT_PERCENT` | Percentual do split (0–100) |
| `PUBLIC_APP_ORIGIN` | Origem pública (CORS + cookies) |
| `URBE_COOKIE_SECURE` | Cookie `Secure` (padrão ligado em produção) |
| `URBE_OPEN_PUBLISH` | Se `0`, só produtores publicam |
| `URBE_PRODUCER_EMAILS` | E-mails promovidos a produtor |
| `URBE_PRODUCER_INVITE` | Convite opcional no cadastro |

## Regras de negócio

1. Usuário autenticado cadastra filme com preço por cota e quantidade total.
2. Usuário compra cota primária via Pix e recebe token de acesso ativo.
3. Dono pode anunciar a cota no mercado secundário.
4. Compra com pagamento usa ordem de checkout: a cota/anúncio fica reservada até a confirmação.
5. Ao comprar o anúncio: a propriedade muda, o token antigo é revogado e um novo é emitido.
6. Ao consumir o token: o link `/watch/...` é de uso único e curto prazo. Só vira `used` se a sessão Bunny abrir.

## Principais endpoints

- `GET /api/health`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/movies` (produtor)
- `GET /api/movies`
- `GET /api/movies/:movieId`
- `GET /api/listings`
- `POST /api/shares/:shareId/listings`
- `POST /api/listings/:listingId/cancel`
- `POST /api/payments/primary/:movieId/checkout`
- `POST /api/payments/listings/:listingId/checkout`
- `POST /api/payments/orders/:orderId/confirm`
- `POST /api/payments/orders/:orderId/cancel`
- `POST /api/payments/webhook/openpix`
- `GET /api/me/shares`
- `GET /api/me/transactions`
- `GET /api/me/orders`
- `POST /api/access/consume`
- `POST /api/access/resume`
- `POST /api/bunny/videos` (produtor + chave Bunny)

## Observações de produção

- Persistência em arquivo JSON é só para desenvolvimento. Em produção use Postgres.
- `PAYMENTS_PROVIDER=mock` aprova pagamento sozinho e só vale fora de produção.
- O webhook precisa de uma máquina no ar: `fly.toml` mantém `min_machines_running = 1`.
- Tokens de sessão ficam em cookie HttpOnly; o player Bunny exige embed assinado em produção.
