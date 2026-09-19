# Bitty

Aplicativo pessoal de automação de cripto em reais, com **Paper Trading**, cotações públicas do Mercado Bitcoin e preparação segura para execução real. Web e Android usam a mesma API e o mesmo banco centralizado; sessões são independentes por dispositivo.

## Executar

```bash
docker compose up -d --build
docker compose run --rm api python -m app.seed
```

Abra `http://localhost:3000`; API/OpenAPI em `http://localhost:8000/docs`.

No Windows também é possível iniciar os dois serviços em segundo plano:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-bitty.ps1
```

Para instalar no Android com sincronização, consulte [docs/android.md](docs/android.md). Não exponha a API diretamente à internet.

## Desenvolvimento sem Docker

Backend: `cd apps/api && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]" && alembic upgrade head && uvicorn app.main:app --reload`.

Frontend: `cd apps/web && pnpm install && pnpm dev`.

No desenvolvimento local, a API inicia um worker Paper embutido. Após iniciar um bot, ele analisa candles e cotações reais em BRL a cada 15 segundos; uma ordem simulada só é criada quando estratégia e controles de risco aprovam. Se o mercado estiver indisponível, o ciclo é ignorado sem enviar ordem. No Docker, Celery/Redis assumem a execução.

## Verificação

```bash
make test
make lint
docker compose build
```

O Compose funciona com defaults locais seguros para Paper Trading. Para qualquer ambiente compartilhado, copie `.env.example` para `.env`, gere `APP_SECRET` aleatório e `ENCRYPTION_MASTER_KEY` com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Nunca reutilize chaves de desenvolvimento.

Em produção, `APP_ENV=production` impede o processo de iniciar com SQLite, cookie sem HTTPS, secret fraco, chave Fernet inválida ou worker embutido. `/ready` só responde 200 quando banco e worker estão disponíveis.

Resultados simulados não garantem resultados futuros.

## Preparação para Binance

1. Gere credenciais exclusivas na Binance Spot Testnet, com permissão apenas para Spot e sem saques.
2. No painel, conecte primeiro a Testnet. A API valida a conta antes de criptografar e salvar as credenciais.
3. Use **Validar ordem de R$ 10**. Esse fluxo chama o endpoint de teste e não envia uma ordem ao livro.
4. Só depois dos testes conecte uma chave Live separada. Nunca reutilize a chave da Testnet.

O worker Paper ignora explicitamente bots que não estejam em modo `PAPER`. O executor automático Live continua bloqueado (`live_executor_enabled=false`) até que reconciliação, testes prolongados e confirmação manual sejam concluídos. Com capital de R$ 100, algumas combinações de percentual de risco e mínimo nocional da exchange podem não gerar ordem; o sistema consulta os filtros atuais antes de aceitar qualquer quantidade.

## Preparação para Mercado Bitcoin

1. Ative o 2FA e crie uma chave de API exclusiva no Mercado Bitcoin.
2. Informe o Client ID e o Client Secret somente no painel local. O segredo é criptografado antes de ser salvo e nunca retorna pela API.
3. A conexão inicial usa apenas OAuth2 e consultas de conta, saldo e mercados `BTC-BRL`, `ETH-BRL` e `SOL-BRL`; nenhuma ordem é criada.
4. Como não existe Testnet pública, o executor Live permanece bloqueado até uma validação manual separada com limite de capital, confirmação explícita e reconciliação de ordens.

O projeto não implementa endpoints de depósito, transferência ou saque do Mercado Bitcoin.

### Executor real inicial (opt-in)

O executor real fica desligado por padrão e exige `REAL_TRADING_ENABLED=true`, diagnóstico aprovado e a frase exata `ATIVAR TRADING REAL`. A primeira versão aceita apenas BTC/BRL e capital de até R$ 100, com:

- no máximo R$ 20 por ordem e R$ 50 preservados em BRL;
- stop-loss de 2% e bloqueio após R$ 2 de perda;
- taxas individuais maker/taker consultadas na conta antes da ativação;
- compra bloqueada quando o ganho estimado não cobre duas taxas taker, spread e 0,5% de margem;
- intenção persistida antes do envio, `externalId` idempotente e pausa em resultado incerto;
- desativação sem venda forçada da posição existente.

Nenhum mecanismo garante lucro ou preço de execução. Ordens a mercado podem sofrer slippage.
