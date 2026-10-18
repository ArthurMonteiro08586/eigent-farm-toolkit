# GUIDE: Eigent.ai Farm + API — как юзать

> Полная карта API: [API_MAP.md](API_MAP.md). Секреты в репо НЕ хранятся — все креды локально в `EIGENT_HOME` (default `C:/Users/User/tmp/eigent`).

## 0. Требования

- Windows, Python 3.11+ (`playwright` для CDP-движка, `camoufox` для headless-движка)
- Реальный Chrome: `C:/Program Files/Google/Chrome/Application/chrome.exe` (или env `CHROME_PATH`)
- Пул GH-аккаунтов с password+TOTP: JSON-массив `[{login, password, totp_secret, email?}, ...]`, путь через env `GH_ACCOUNTS`
- Sidecar-солвер капч (опционально): `SIDE=http://127.0.0.1:8878/solve`
- Residential-прокси (опционально): `PROXY=http://user:***@host:port`

## 1. Фарм Pro-триалов ($99.99 план, 7 дней)

```bash
# CDP-движок (реальный Chrome, основной):
python eigent_farm_cdp.py N [start_idx]     # N аккаунтов, старт с индекса пула

# Camoufox-движок (headless, альтернатива):
python eigent_farm.py N [start_idx]
```

Флоу одного аккаунта (~3 мин): GH OAuth (pw+TOTP) → www.eigent.ai/pricing → Pro trial →
Stripe Checkout → карта (chkr.cc BIN, генерируется на лету) → USA / ZIP 10001 →
hCaptcha → `Payment successful` → парсинг дашборда (credits/trial_ends) → запись в `eigent_bank.jsonl`.

Результаты: `eigent_bank.jsonl` (jsonl: idx, gh_login, card_tail, checkout, result, credits, trial_ends),
лог `farm_cdp.log` / `farm.log`, использованные индексы `eigent_used_gh.txt`.

**Текущий статус капчи (18.10):** Stripe переключился на hcaptcha-invisible + human-security —
видимого чекбокса нет, CDP-клик не проходит (`cb_clicks=0`). Рабочие пути:
1. Ручной гибрид: скрипт доводит до Stripe submit, человек 1 клик (так активирован первый триал).
2. 2captcha hCaptcha Enterprise для invisible sitekey + инжект токена.
3. Sidecar `real_page=true` при появлении интерактивного челленджа.

## 2. Реверс API: токен + ключ из аккаунта (без браузера дальше шага 1)

```bash
python token_extract.py [idx]
```

Что делает: GH OAuth через CDP → cookie `stack-access` (JWT) →
`POST https://dev.eigent.ai/api/v1/login-by_stack?token=<jwt>` → Bearer-токен →
`GET /api/v1/user/key` → **`sk-*` ключ + `https://eigent-proxy.eigent.ai/`** →
E2E probe (`/key/info`, `/chat/completions`).

Выход: `eigent_api_creds.json` = `{token, user_id, email, key{value, api_url}, models, credits, subscription}`.

Важно: `www.eigent.ai/api` proxy отдаёт 500 — все вызовы только через `dev.eigent.ai`.

## 3. Использование API

```bash
# ключ (статичный, живёт пока аккаунт жив)
curl https://dev.eigent.ai/api/v1/user/key -H "Authorization: Bearer $EIGENT_TOKEN"

# баланс / подписка / модели
curl https://dev.eigent.ai/api/v1/user/current_credits -H "Authorization: Bearer $EIGENT_TOKEN"
curl https://dev.eigent.ai/api/v1/subscription        -H "Authorization: Bearer $EIGENT_TOKEN"
curl "https://dev.eigent.ai/api/v1/cloud-models?kind=chat" -H "Authorization: Bearer $EIGENT_TOKEN"

# LLM-прокси (LiteLLM, OpenAI-compatible) — только sk-ключ, JWT не принимается
curl https://eigent-proxy.eigent.ai/chat/completions \
  -H "Authorization: Bearer $EIGENT_SK_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gpt-6-sol","messages":[{"role":"user","content":"hi"}]}'

# живость ключа без расхода кредитов
curl "https://eigent-proxy.eigent.ai/key/info?key=$EIG…KEY" -H "Authorization: Bearer $EIGENT_SK_KEY"
```

**Billing-гейт (18.10):** любой chat-запрос → `403 "You're out of credits"` даже на активном
Pro-trial (1500 credits, 300 daily). Хук смотрит `daily_credits` (=0), не trial-балансы.
После ~2 отказов ключ авто-блокируется (`401 Key is blocked`). Ретест после их daily-sync (00:00 UTC).
`/key/info` при этом 200: max_budget 3.5, spend 0.0 — сам LiteLLM-слой жив.

20 моделей: gpt-6-astra/sol/luna · claude-opus-5-5, claude-fable-5-1, claude-sonnet-5 (min_plan=plus) ·
grok-4-7 (plus) · gemini-4-argon · glm-5.3(-flash) · qwen3.8-max · kimi-k3 · deepseek-v4-pro/flash ·
minimax-m3 · tencent/hy3 · inclusionai/ling-2.6-1t · eigent (low_balance_allowed).

## 4. Дашборд

```bash
python dashboard.py            # http://127.0.0.1:8750
EIGENT_HOME=/path/to/data python dashboard.py   # если данные не в tmp/eigent
```

Показывает: банк аккаунтов (статусы/триалы/кредиты), текущие API-креды (маскированные),
статистику GH-пула, tail логов фермы, live-пробы прокси (`/health/liveliness`, `/key/info`).
Только чтение локальных файлов, stdlib-only, наружу не слушает (127.0.0.1).

## 5. Питфолы

- `Page.evaluate: Execution context was destroyed` на OAuth-кликах — обычно benign (навигация), оборачивать в try/except.
- Stripe country combobox: click → type "United States" → ArrowDown → Enter (не fill).
- `--start-minimized` у Chrome ломает captcha (visibilityState) — только headed.
- Минимизировать окно Chrome во время капчи нельзя.
- Ключ прокси статичный per-user; после блок-а (`401 Key is blocked`) нужен новый аккаунт.
- GH used-индексы: `eigent_used_gh.txt`, один индекс = одна попытка оплаты.
- Карты: только Luhn-валидные из `chkr_cardgen.py` (BIN client-side валидируется Stripe до hCaptcha).
