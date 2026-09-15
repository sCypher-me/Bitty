# Deploy controlado

Use `docker compose up -d --build`. A API aplica a migration antes de iniciar; worker e scheduler usam Redis; dados ficam nos volumes PostgreSQL/Redis. Confirme `/health`, `/ready`, logs e heartbeat antes de expor o frontend.

Produção usa duas camadas:

- Vercel: `apps/web`, domínio público e proxy de `/api/v1/*`.
- Render Blueprint: `bitty-api`, PostgreSQL, Redis, `bitty-worker` e `bitty-scheduler` definidos em `render.yaml`.

No Render, informe manualmente o mesmo `ENCRYPTION_MASTER_KEY` nos três processos, secrets fortes para os workers e a URL Vercel em `FRONTEND_URL`. Mantenha `REAL_TRADING_ENABLED=false`. Depois do backend publicar, configure `API_INTERNAL_URL=https://<backend-render>` no projeto Vercel e use `apps/web` como Root Directory.

O plano de worker contínuo pode ser cobrado. Revise o custo mostrado pelo provedor antes de confirmar o Blueprint; não há garantia de execução 24/7 gratuita. Produção também requer backups testados e monitoramento de `/ready`. Trading real continua bloqueado.

Critérios antes do APK final:

1. `/ready` retorna banco e worker como `true`.
2. Cadastro, login, refresh e logout passam no domínio Vercel.
3. Paper Bot continua rodando após fechar o navegador.
4. WebSocket funciona ou o painel mostra o fallback de atualização automática.
5. `BITTY_APP_URL` recebe a URL HTTPS validada da Vercel antes de `cap sync android`.
