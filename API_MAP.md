# Eigent.ai API Reverse (2026-10-18)

Public source: github.com/eigent-ai/eigent (TS desktop app + Python local backend).
Backend API: `https://dev.eigent.ai/api/v1/*` (www.eigent.ai/api proxy = 500, do not use).
LLM proxy: `https://eigent-proxy.eigent.ai/` — **LiteLLM**, OpenAI-compatible.

## Auth chain (verified E2E)

1. GitHub OAuth via Stack Auth on `www.eigent.ai/signin`
   - client_id `aa49cdd0-318e-46bd-a540-0f1e5f2b391f` (public, in bundle)
   - Stack session lands in cookie `stack-access` (URL-encoded JSON array, element [1] = JWT)
2. `POST https://dev.eigent.ai/api/v1/login-by_stack?token=<stack_jwt>` body `{"token": "<stack_jwt>"}`
   → `{"token": "<eigent bearer, 263 chars>", "email", "user_id", ...}`
3. With `Authorization: Bearer <eigent token>`:
   - `GET /api/v1/user` → profile
   - `GET /api/v1/user/key` → `{"value": "sk-...", "api_url": "https://eigent-proxy.eigent.ai/"}` (static per user, 39 chars)
   - `GET /api/v1/user/current_credits` → `{"credits": N, "daily_credits": N}`
   - `GET /api/v1/subscription` → plan/trial state incl. `trial_daily_credits_remaining`
   - `GET /api/v1/cloud-models?kind=chat` → 20 models

## Proxy usage

- `POST {api_url}/chat/completions` (also `/v1/chat/completions`, `/responses`)
- Auth: `Authorization: Bearer sk-...` (LiteLLM virtual key ONLY; user JWT rejected 401)
- `GET {api_url}/key/info?key=sk-...` → 200 with user key (max_budget 3.5 free tier, spend, models)
- `GET {api_url}/health/liveliness` → 200 `"I'm alive!"`

## Models (cloud-models kind=chat, 20)

gpt-6-astra / gpt-6-sol (default) / gpt-6-luna (azure) · eigent (openai-compat, low_balance_allowed) ·
gemini-4-argon (gemini) · claude-fable-5-1 / claude-opus-5-5 / claude-sonnet-5 (anthropic, min_plan=plus) ·
grok-4-7 (min_plan=plus) · openai/gemini-3.8-flash · openai/muse-spark-1.3 · z-ai/glm-5.3(-flash) ·
qwen/qwen3.8-max · moonshotai/kimi-k3 · deepseek-v4-pro/flash · minimax/minimax-m3 · tencent/hy3 ·
inclusionai/ling-2.6-1t

## Billing gate (the blocker, 2026-10-18)

- ANY `/chat/completions` call → `403 {"error":{"message":"You're out of credits. Please top up to continue."}}`
  even on an ACTIVE Pro trial (credits 1500, trial_daily_credits_remaining 300, key max_budget 3.5, spend 0.0, blocked null).
- After ~2 rejected calls the key flips to `401 "Key is blocked. Update via /key/unblock if you're admin"` (auto-block; unblock needs admin key).
- Custom billing hook reads `daily_credits` (=0 on all accounts), NOT subscription/trial balances.
- Desktop app sends plain OpenAI calls with the same key — no extra billing headers in source → same gate expected app-side until their daily sync provisions `daily_credits`.

## Full /api/v1 endpoint map (from source)

auth/oauth/token · chat/files(/upload,/download) · chat/histories(/grouped) · chat/history ·
chat/project · chat/share(/info,/playback) · chat/snapshots · chat/steps/playback ·
cloud-models · config/info · configs · connectors/connections · connectors/oauth/authorizations ·
connectors/providers · execution(/subscribe) · login-by_stack · mcp/import/local · mcp/import/remote ·
mcp/install · mcp/users · mcps · oauth/(provider)/callback · oauth/linkedin/login · provider(s)(/prefer) ·
redirect/callback · register · remote-control/bridge/subscribe · remote-control/sessions ·
remote-sub-agent-providers · server/capabilities · spaces(/legacy) · subscription · trigger ·
user · user/auto-login · user/current_credits · user/invite_code · user/key · user/privacy ·
workspace-bundles

## Tooling

- `token_extract.py [idx]` — GH OAuth (pw+TOTP) → stack-access cookie → login-by_stack → dumps
  token/key/api_url/models/credits/subscription to `eigent_api_creds.json` + E2E proxy probe.
- Reuse for a gateway: token refresh not needed for proxy (sk-key static); re-run extractor per account.
