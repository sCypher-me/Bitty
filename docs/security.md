# Segurança

- Senhas são derivadas com Argon2 e nunca armazenadas em texto puro; CORS é restrito e respostas recebem headers defensivos.
- O access token dura 15 minutos e fica em cookie `HttpOnly`.
- Cada navegador/WebView possui uma `DeviceSession` própria com refresh token rotativo; somente o hash SHA-256 é persistido.
- Logout revoga apenas a sessão atual. Tokens revogados ou expirados são recusados também no WebSocket.
- Credenciais de corretora são criptografadas com Fernet e nunca retornam pela API.
- Toda leitura privada filtra `user_id`; IDs fornecidos pelo cliente nunca bastam para autorizar acesso.
- Produção falha ao iniciar se cookies HTTPS, PostgreSQL central, chave Fernet e worker externo não estiverem configurados.
- O executor de dinheiro real permanece desabilitado e os testes não enviam ordens reais.
- O produto é spot-only, sem short, margem, futuros, alavancagem, transferências ou saques.

Antes de publicar, rode a varredura de segredos sobre a lista rastreada pelo Git. `.env`, bancos, logs, APKs, keystores, caches e artefatos estão ignorados.
