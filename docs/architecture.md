# Arquitetura

Monólito modular: Next.js consome a API FastAPI; PostgreSQL persiste dados privados com `user_id`; Celery/Redis executa coordenação, heartbeat e reconciliação. O fluxo financeiro é `Market data → Strategy signal → Risk Manager → Order Manager → Execution Adapter → Portfolio`. Estratégia e risco não conhecem o modo de execução.

Reinícios são fail-closed: bots entram em `STARTING`, reconciliam ordens/posições e só então podem ficar `ACTIVE`. Locks Redis `bot:{id}:execution` devem envolver cada ciclo do worker ao evoluir o scheduler de demonstração para feeds externos.
