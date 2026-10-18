# eigent-farm-toolkit

Масс-фарм Pro-триалов eigent.ai (7 дней, $99.99/мес план) — полный E2E без ручного браузера.
**+ реверс API**: auth-цепочка, LiteLLM-прокси, карта 50+ эндпоинтов.

- 📖 **[GUIDE.md](GUIDE.md)** — как юзать всё (фарм, token-экстрактор, API-вызовы, дашборд, питфолы)
- 🗺 **[API_MAP.md](API_MAP.md)** — реверс API: GH OAuth → stack JWT → login-by_stack → sk-ключ → eigent-proxy (LiteLLM), billing-гейт, 20 моделей
- 📊 **`dashboard.py`** — локальный дашборд (stdlib, `http://127.0.0.1:8750`): банк триалов, API-креды (маскированные), GH-пул, tail логов, live-probe прокси без расхода кредитов
- 🔑 **`token_extract.py [idx]`** — GH-акк → Bearer-токен → sk-ключ + api_url → E2E probe → `eigent_api_creds.json`

## Флоу (проверен E2E, ~3 мин/акк)

1. **GitHub OAuth** — eigent.ai/signin → Continue with GitHub → логин+TOTP → Authorize
2. **Pricing** — вторая кнопка "Start 7 day free trial" = Pro план ($99.99/мес)
3. **Stripe Checkout** — карта chkr.cc BIN `5424322339` (client-side генерация, Luhn),
   billing **USA + ZIP 10001** (350 5th Avenue, New York, NY)
4. **hCaptcha** — три пути (по убыванию надёжности):
   - **Real Chrome (CDP)** — residential IP + живой Chrome: чекбокс проходит ОДНИМ
     кликом без визуального челленджа. Клик через playwright `connect_over_cdp` —
     trusted-событие, фокус окна не нужен
   - невидимая (camoufox): иногда авто-проходит без взаимодействия
   - sidecar-солвер (`POST /solve {type:hcaptcha, sitekey, url, timeout_s}`) → токен
     инжектится во все фреймы (`window.hcaptcha.setResponse` + `textarea[name*=captcha]`
     + `postMessage captcha-success`). Внимание: синтетический route-intercept solve
     может висеть >240с (408) — только как fallback
   - для ручного окна под фокус-захватом — `force_fg_click.py` (AttachThreadInput + ALT-трюк +
     SetForegroundWindow, клик только когда GetForegroundWindow()==hwnd)
5. **Payment successful** → триал 7 дней, 1000 credits total / 300 в день
6. Запись в банк `eigent_bank.jsonl` (idx, gh_login, card_tail, result, credits, ref_code)

## Файлы

- `eigent_farm_cdp.py` — **основной** батч-фармер на real Chrome через CDP:
  `python eigent_farm_cdp.py N [start_idx]` (свежий Chrome-профиль на акк, порт 9400+,
  пэйсинг 75–140с, чекбокс-клик через CDP, sidecar как fallback, авто-чистка профилей)
- `eigent_farm.py` — альтернативный батч-фармер на camoufox (headless, PROXY-поддержка)
- `chkr_cardgen.py` — оффлайн-генератор карт BIN 5424322339 (Luhn, без API — live-check
  endpoint'ы chkr.cc отдают 429 и для триала не нужны)
- `force_fg_click.py` — нативный клик в Windows-окно с принудительным foreground
  (обход «Foreground увели» для hCaptcha-чекбоксов)
- `stripe_sitekeys.txt` — известные Stripe hCaptcha sitekey'и (fallback; основной —
  динамический захват из getcaptcha-запросов)
- `token_extract.py` — экстрактор API-кредов из GH-аккаунта (см. GUIDE.md §2)
- `dashboard.py` — локальный веб-дашборд статуса (см. GUIDE.md §4)
- `GUIDE.md` / `API_MAP.md` — гайд использования + карта реверса API

## Env

- `GH_ACCOUNTS` — путь к пулу GitHub-акков (JSON: login/password/totp), по умолчанию
  локальный (в репо НЕ входит)
- `SIDE` — sidecar solve endpoint, по умолчанию `http://127.0.0.1:8878/solve`
- `CHROME_PATH` — путь к chrome.exe (CDP-движок)
- `PROXY` — опционально `http://user:pass@host:port` (camoufox-движок)
- `BIN_OVERRIDE` — опциональный другой BIN для chkr_cardgen

## Требования

- Python 3.11+, `playwright` (CDP-движок — подключается к системному Chrome, браузер
  не качает), `camoufox` для альт-движка (`python -m camoufox fetch`)
- Пул GH-аккаунтов с password + TOTP seed
- Sidecar hCaptcha-солвер (любой, принимающий `{type:"hcaptcha", sitekey, url}`)

## Pitfalls (проверено на практике)

- playwright `evaluate`, который сам кликает кнопку с навигацией → «Execution context
  was destroyed» — это УСПЕХ; оборачивать в try/except
- Stripe country — combobox: клик → type "United States" → ArrowDown → Enter
  (pointer-клик по опции нестабилен)
- `--start-minimized` Chrome влияет на visibilityState — hCaptcha капризничает; запускать headed
- После Payment successful: Spendable credits и referral-код парсятся с главной дашборда

## Заметки

- Residential IP: hCaptcha-чекбокс проходит без челленджа. DC IP — риск rate-limit Stripe/GitHub.
- Квота триалов может быть на платёжный отпечаток — при массовом decline менять BIN.
- После активации: скачать eigent-приложение, логин через тот же GH-акк.
- Отмена подписки (чтобы не списало $99.99 после триала) — через Stripe-ссылку в дашборде.
