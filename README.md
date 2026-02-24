# Urbe

Plataforma web para emissão e negociação de **cotas de visualização** de filmes.

Cada cota representa **1 visualização única**. Ao transferir a cota para outro proprietário:

- o token antigo é revogado,
- um novo token é emitido para o novo dono,
- somente o token ativo permite liberar o player.

A reprodução é integrada à Bunny.net por URL de embed (com assinatura opcional via `BUNNY_STREAM_EMBED_TOKEN_KEY`).

## Stack

- Python 3.9+ (sem frameworks externos)
- API HTTP + frontend estático
- Persistência local em JSON (`data/urbe-db.json`)
- Integração Bunny Stream via API REST
- Integração de pagamentos com provedor configurável (`mock` e `stripe`)

## Setup

```bash
cp .env.example .env
python3 -m py_backend.server
```

Aplicação: `http://localhost:3000`

## Deploy rapido (Railway)

Arquivos prontos para copiar variaveis:

- `deploy/railway.mock.env.example`
- `deploy/railway.stripe.env.example`

Guia passo a passo:

- `deploy/RAILWAY_DEPLOY.md`

## Variáveis de ambiente

Arquivo: `.env`

- `PORT`: porta do servidor
- `DB_FILE`: arquivo de persistência
- `SESSION_DURATION_DAYS`: duração da sessão
- `CHECKOUT_RESERVATION_MINUTES`: minutos de reserva da cota/anúncio durante checkout pendente
- `PLAYBACK_SESSION_SECONDS`: tempo (segundos) do link de reprodução one-time
- `BUNNY_STREAM_API_KEY`: chave da API Bunny (necessária para criar vídeo via endpoint `/api/bunny/videos`)
- `BUNNY_STREAM_LIBRARY_ID`: biblioteca padrão Bunny
- `BUNNY_STREAM_EMBED_TOKEN_KEY`: chave para assinatura do embed
- `BUNNY_IFRAME_HOST`: host do iframe (padrão `https://iframe.mediadelivery.net`)
- `PAYMENTS_PROVIDER`: `mock` ou `stripe`
- `PAYMENTS_CURRENCY`: moeda (ex: `BRL`)
- `PAYMENTS_CHECKOUT_SUCCESS_URL`: URL de retorno do checkout (aceita placeholders `{ORDER_ID}` e `{CHECKOUT_SESSION_ID}`)
- `PAYMENTS_CHECKOUT_CANCEL_URL`: URL de cancelamento (aceita placeholders `{ORDER_ID}` e `{CHECKOUT_SESSION_ID}`)
- `STRIPE_SECRET_KEY`: chave secreta Stripe (obrigatória quando `PAYMENTS_PROVIDER=stripe`)
- `STRIPE_API_BASE`: base da API Stripe (padrão `https://api.stripe.com/v1`)

## Regras de negócio implementadas

1. Usuário autenticado cadastra filme com preço por cota e quantidade total.
2. Usuário compra cota primária e recebe token de acesso ativo.
3. Dono pode anunciar a cota no mercado secundário.
4. Compra com pagamento usa ordem de checkout:
   - a cota/anúncio é reservada temporariamente,
   - a transferência só acontece após confirmação de pagamento.
5. Ao comprar o anúncio:
   - propriedade da cota muda,
   - token antigo é revogado,
   - novo token é emitido para o comprador.
6. Ao consumir token para assistir:
   - é emitido um link `/watch/...` de uso único e curto prazo (amarrado ao navegador por cookie),
   - ao abrir esse link com sucesso, token vira `used` e cota vira `consumed`,
   - visualização não pode ser repetida.

## Principais endpoints

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/movies` (autenticado)
- `GET /api/movies`
- `GET /api/movies/:movieId`
- `POST /api/movies/:movieId/buy`
- `GET /api/listings`
- `POST /api/shares/:shareId/listings`
- `POST /api/listings/:listingId/buy`
- `POST /api/listings/:listingId/cancel`
- `GET /api/payments/config`
- `POST /api/payments/primary/:movieId/checkout`
- `POST /api/payments/listings/:listingId/checkout`
- `POST /api/payments/orders/:orderId/confirm`
- `POST /api/payments/orders/:orderId/cancel`
- `GET /api/me/shares`
- `GET /api/me/transactions`
- `GET /api/me/orders`
- `POST /api/access/consume`
- `POST /api/bunny/videos` (autenticado + Bunny API key)

## Testes

```bash
python3 -m unittest py_backend.test_service
```

Os testes validam os cenários críticos:

- revogação do token antigo após revenda;
- consumo único do token.
- checkout primário com aprovação de pagamento;
- checkout de revenda com reserva e confirmação posterior.

## Observações de produção

- Esta versão usa persistência em arquivo JSON (MVP). Para produção, trocar por banco transacional.
- Em `PAYMENTS_PROVIDER=mock`, pagamentos são aprovados automaticamente para desenvolvimento.
- Para produção, use `PAYMENTS_PROVIDER=stripe`, proteja segredos e adicione webhooks para conciliação financeira.
- Adicionar antifraude, trilha de auditoria e assinatura forte de requests para hardening.
