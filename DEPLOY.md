# TransitFlow — инструкция по запуску и деплою (ручные шаги)

Это пошаговая инструкция **для человека**. Здесь всё, что Claude Code не может
сделать за тебя: создать аккаунты, нажать кнопки в дашборде, ввести секреты.

На текущем этапе (Этап 0) готов **только backend**: БД, сид, логин.
Фронтенда ещё нет — это нормально, он будет на Этапе 1. Цель этого деплоя —
поднять «hello world + БД» на Railway уже сегодня, как требует раздел 9 спеки
(не оставлять деплой на последнюю ночь).

Что будет работать после деплоя:
- `GET /api/health` → `{"status":"ok"}`
- `POST /api/auth/login` → вход тремя демо-аккаунтами
- `GET /docs` → интерактивная Swagger-документация

---

## Содержание
1. [Глоссарий (что есть что)](#0-глоссарий)
2. [Часть A. Проверка локально (по желанию, 10 мин)](#часть-a--проверка-локально)
3. [Часть B. Залить код на GitHub](#часть-b--залить-код-на-github)
4. [Часть C. Деплой на Railway](#часть-c--деплой-на-railway)
5. [Часть D. Проверка задеплоенного](#часть-d--проверка-что-всё-работает)
6. [Часть E. Если что-то сломалось](#часть-e--типичные-проблемы)

---

## 0. Глоссарий

| Термин | Что это |
|---|---|
| **Backend** | Серверная часть на Python (FastAPI). Лежит в папке `backend/`. |
| **Postgres** | База данных. Локально — в Docker, на проде — сервис Railway. |
| **DATABASE_URL** | Строка подключения к БД. Главная переменная окружения. |
| **Сид (seed)** | Скрипт `backend/seed.py`, заполняет БД синтетикой. Идемпотентный — повторный запуск не дублирует данные. |
| **Railway** | Хостинг, где будут жить и приложение, и база. |
| **Демо-аккаунты** | `shipper@demo` / `carrier@demo` / `analyst@demo`, пароль у всех — `demo123`. |

> ⚠️ **Самое важное про DATABASE_URL.** Мы используем драйвер **psycopg 3**.
> Поэтому строка подключения ОБЯЗАНА начинаться с `postgresql+psycopg://`,
> а НЕ с `postgresql://`. Railway по умолчанию даёт URL со схемой
> `postgresql://` — её придётся поправить (как — показано ниже). Если этого
> не сделать, приложение упадёт с ошибкой про psycopg2.

---

## Часть A — Проверка локально

Этот раздел не обязателен для деплоя, но полезен: убедиться, что всё
поднимается на твоей машине. Если хочешь сразу деплоить — переходи к [Части B](#часть-b--залить-код-на-github).

Нужен **Docker Desktop** (для локального Postgres) и **Python 3.11+**.

Все команды — в PowerShell, из корня проекта `C:\Users\ASUS\Desktop\TransitFlow`.

### A.1. Поднять Postgres в Docker
```powershell
docker compose up -d db
```
Проверить, что контейнер «healthy»:
```powershell
docker inspect -f '{{.State.Health.Status}}' transitflow_db
```
Должно вывести `healthy` (если `starting` — подожди 10 секунд и повтори).

### A.2. Создать виртуальное окружение и поставить зависимости
```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### A.3. Создать файл backend\.env
Скопируй пример и оставь как есть (для локали значения уже правильные):
```powershell
Copy-Item backend\.env.example backend\.env
```
Содержимое `backend\.env` для локального запуска:
```
DATABASE_URL=postgresql+psycopg://transitflow:transitflow@localhost:5432/transitflow
JWT_SECRET=dev-secret-change-me
JWT_EXPIRE_MINUTES=720
ANTHROPIC_API_KEY=
```
> `.env` намеренно в `.gitignore` и НЕ попадёт в GitHub — это правильно,
> секреты в репозиторий не коммитим.

### A.4. Залить синтетику в БД
```powershell
cd backend
.venv\Scripts\python.exe seed.py
```
Ожидаемый вывод: ~42 000 строк трафика, 78 заявок, 17 броней и т.д.

### A.5. Проверить, что данные легли и паттерны видны
```powershell
$env:PYTHONUTF8=1
.venv\Scripts\python.exe check_seed.py
```
Увидишь счётчики, тепловую карту загрузки порта (пик днём, спад ночью)
и калибровку «~12 млн т/год».

### A.6. Запустить сервер
```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```
Открой в браузере:
- http://127.0.0.1:8000/api/health → `{"status":"ok"...}`
- http://127.0.0.1:8000/docs → Swagger. Нажми на `POST /api/auth/login`,
  «Try it out», тело:
  ```json
  { "email": "shipper@demo", "password": "demo123" }
  ```
  → вернётся `access_token`. Логин работает.

Остановить сервер — `Ctrl+C`. Погасить базу, когда не нужна:
```powershell
docker compose down
```
(добавь `-v`, если хочешь стереть и данные тоже).

---

## Часть B — Залить код на GitHub

Репозиторий уже привязан к `https://github.com/makserik1999-web/TransitFlow.git`.
Нужно просто запушить накопленные коммиты.

Из корня проекта:
```powershell
git push -u origin main
```
Если попросит логин — введи свой GitHub-аккаунт (для пароля используется
**Personal Access Token**, а не обычный пароль; создаётся на github.com →
Settings → Developer settings → Tokens).

Проверь, что на github.com/makserik1999-web/TransitFlow появились папки
`backend/`, `frontend/`, файлы `SPEC_TransitFlow.md`, `DEPLOY.md`,
`docker-compose.yml`. Файла `.env` там быть НЕ должно (это правильно).

---

## Часть C — Деплой на Railway

Делается через сайт https://railway.app — **CLI не нужен**.

### C.1. Создать проект из GitHub
1. Зайди на https://railway.app, войди через GitHub.
2. **New Project** → **Deploy from GitHub repo** → выбери `TransitFlow`.
   (Если Railway не видит репозиторий — нажми «Configure GitHub App»
   и дай доступ к этому репо.)
3. Railway создаст сервис из репозитория. Назовём его **app**.

### C.2. Добавить базу Postgres
1. В том же проекте: **New** → **Database** → **Add PostgreSQL**.
2. Появится сервис **Postgres**. Он сам поднимется за ~1 минуту.

### C.3. Указать, что приложение — в папке backend
Открой сервис **app** → вкладка **Settings**:
1. **Root Directory**: впиши `backend`
   (так Railway увидит `requirements.txt` и соберёт Python-приложение).
2. **Start Command**: впиши ровно это:
   ```
   python seed.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
   > Почему так: `seed.py` идемпотентен — на первом запуске он наполнит
   > базу, на последующих просто пропустит уже залитое. Это гарантирует,
   > что прод-база засеяна, и тебе не надо сеять руками.

### C.4. Прописать переменные окружения сервиса app
Сервис **app** → вкладка **Variables** → добавь три переменные:

1. **DATABASE_URL** — впиши именно это значение (со схемой `+psycopg`!):
   ```
   postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
   ```
   Это «ссылочная переменная»: Railway сам подставит логин/пароль/хост из
   сервиса Postgres. Скобки `${{...}}` копируй как есть.
   > Если у твоего сервиса БД другое имя (не `Postgres`), замени `Postgres`
   > в скобках на это имя.

2. **JWT_SECRET** — длинная случайная строка (не оставляй дефолт!). Например
   сгенерируй локально:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   и вставь результат как значение.

3. **ANTHROPIC_API_KEY** — *опционально*. На Этапе 0 не нужен (AI-сводки ещё
   нет). Можно не добавлять или оставить пустым.

> `PORT` Railway задаёт автоматически — отдельно прописывать не надо.

### C.5. Открыть приложение наружу (домен)
Сервис **app** → **Settings** → раздел **Networking** → **Generate Domain**.
Получишь публичный адрес вида `https://transitflow-production-xxxx.up.railway.app`.

### C.6. Дождаться деплоя
Вкладка **Deployments** покажет лог сборки. Жди статус **Success / Active**.
Первый деплой идёт 2–4 минуты (ставит зависимости, потом сеет базу).

---

## Часть D — Проверка, что всё работает

Подставь свой домен из шага C.5.

1. **Health-check** — открой в браузере:
   ```
   https://ТВОЙ-ДОМЕН.up.railway.app/api/health
   ```
   Должно вернуть `{"status":"ok","service":"transitflow"}`.

2. **Swagger** — открой:
   ```
   https://ТВОЙ-ДОМЕН.up.railway.app/docs
   ```
   `POST /api/auth/login` → Try it out → тело:
   ```json
   { "email": "analyst@demo", "password": "demo123" }
   ```
   → должен вернуться `access_token`. Деплой удался.

3. **Что база засеяна** — в логах деплоя (Deployments → лог) на первом
   запуске увидишь строки сида: `traffic_history: 42... строк`,
   `bookings: ... броней`. На повторных деплоях — `уже содержит ... — пропуск`.

✅ Если оба пункта 1 и 2 зелёные — Этап 0 задеплоен. Сохрани публичный URL,
он понадобится для сдачи (письмо к 08:00 12 июня, раздел 9 спеки).

---

## Часть E — Типичные проблемы

| Симптом | Причина | Решение |
|---|---|---|
| В логе `ModuleNotFoundError: psycopg2` или ошибка диалекта | DATABASE_URL со схемой `postgresql://` | Поменяй на `postgresql+psycopg://...` (см. C.4) |
| `Connection refused` / не видит БД | Сервис Postgres не привязан или имя в `${{Postgres.*}}` другое | Проверь имя сервиса БД и подставь его в переменную |
| Деплой падает на `seed.py` | БД ещё не готова в момент старта | Передеплой (Deployments → Redeploy): база уже поднимется |
| `401` на логине | Неверный email/пароль | Только демо-аккаунты: `*@demo` / `demo123` |
| Локально `docker compose up` ругается на pipe | Docker Desktop не запущен | Запусти Docker Desktop, дождись зелёного значка, повтори |
| `git push` просит пароль и отвергает | GitHub больше не принимает пароль | Используй Personal Access Token вместо пароля |
| Railway не показывает репозиторий | Нет доступа GitHub App | «Configure GitHub App» → дай доступ к TransitFlow |

---

## Краткий чек-лист (для скорости)

- [ ] `git push -u origin main` — код на GitHub
- [ ] Railway: New Project → from GitHub repo → TransitFlow
- [ ] Railway: New → Database → PostgreSQL
- [ ] app → Settings → Root Directory = `backend`
- [ ] app → Settings → Start Command = `python seed.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- [ ] app → Variables → `DATABASE_URL` (со схемой `+psycopg`), `JWT_SECRET`
- [ ] app → Settings → Networking → Generate Domain
- [ ] Проверить `/api/health` и `/docs` на домене
- [ ] Сохранить публичный URL для сдачи
