# Semantic Layer Agent

AI-агент для аналитики данных через естественный язык. Задаёте вопрос на русском — получаете данные из базы.

**Архитектура:** Вопрос → FAISS (семантический поиск) → LLM (генерация запроса) → Cube.js (выполнение) → Ответ

## Структура проекта

```
├── cube-jira/                  # Cube.js — семантический слой (удалённый сервер)
│   ├── model/cubes/            # YAML-модели данных (issues, users, sprints...)
│   ├── semantic/               # Glossary, examples, конфиг семантического слоя
│   ├── tools/                  # Инструменты генерации моделей
│   │   ├── 01_data_loader.py   #   Автогенерация моделей из БД + GigaChat + JIRA KB
│   │   ├── 02_build_faiss.py   #   Построение FAISS-индекса
│   │   ├── embedding_utils.py  #   Фабрика эмбеддингов (HuggingFace / GigaChat)
│   │   ├── db_sources.py       #   Коннекторы GreenPlum / Hive + Kerberos
│   │   ├── kerberos_auth.py    #   Утилита Kerberos-аутентификации
│   │   └── config.yml          #   Конфигурация инструментов
│   ├── docker-compose.yml      # Запуск Cube в Docker
│   └── .env.example            # Шаблон подключения к БД
│
├── jira-ai-poc/                # AI-агент (FastAPI веб-сервер)
│   └── agent/
│       ├── universal_agent.py  # Ядро: FAISS + LLM + Cube API
│       ├── prompt_builder.py   # Построение промптов для LLM
│       ├── semantic_app.py     # FastAPI веб-интерфейс (http://localhost:8000)
│       ├── semantic_config.py  # Загрузка semantic-конфигурации
│       ├── embedding_utils.py  # Фабрика эмбеддингов
│       ├── db_sources.py       # Коннекторы GreenPlum / Hive
│       ├── kerberos_auth.py    # Kerberos-аутентификация
│       └── .env.example        # Шаблон: OpenAI / GigaChat ключи
│
└── closed-env-package/         # Пакет для закрытого контура (JupyterLab, без интернета)
    ├── 01_data_loader.py       # Автогенерация моделей из БД + GigaChat + внешняя KB
    ├── 02_build_faiss.py       # Построение FAISS-индекса
    ├── 03_agent.ipynb          # Jupyter-ноутбук агента
    ├── validate.py             # Валидация окружения перед деплоем
    ├── kb/                     # Knowledge Base файлы
    │   ├── jira_kb.yml         #   Подсказки для JIRA (22 таблицы)
    │   └── template_kb.yml     #   Шаблон для своего домена
    ├── db_sources.py           # GreenPlum / Hive + Kerberos
    ├── kerberos_auth.py        # Kerberos-тикеты
    ├── embedding_utils.py      # Фабрика эмбеддингов
    ├── config.yml              # Единая конфигурация
    └── 00_load_duckdb.py       # Загрузка Parquet/CSV → DuckDB
```

## Компоненты

### cube-jira — Семантический слой
Cube.js проект с 6 ручными моделями (issues, projects, users, sprints, activity, references) + инструменты для автогенерации новых моделей из БД.

### jira-ai-poc — AI-агент
FastAPI-приложение с веб-интерфейсом. Принимает вопрос на русском языке, ищет релевантные метрики через FAISS, генерирует Cube-запрос через LLM (OpenAI/GigaChat), выполняет его и возвращает результат.

### closed-env-package — Пакет для закрытого контура
Автономный пакет для JupyterLab без интернета. Включает data_loader с встроенной JIRA Knowledge Base (описания 22 стандартных таблиц JIRA), поддержку GreenPlum/Hive через Kerberos, и Jupyter-ноутбук агента.

## Быстрый старт

### 1. Cube.js (семантический слой)

```bash
cd cube-jira
cp .env.example .env
# Заполните .env: хост, БД, пользователь, пароль
npm install
docker-compose up -d
# Проверка: http://localhost:4000
```

### 2. AI-агент

```bash
cd jira-ai-poc/agent
cp .env.example .env
# Заполните .env: OPENAI_API_KEY или GIGACHAT_CREDENTIALS, CUBE_BASE_URL
pip install -r requirements.txt
python semantic_app.py
# Откройте: http://localhost:8000
```

### 3. Генерация моделей из БД

```bash
cd cube-jira/tools
# Отредактируйте config.yml
python 01_data_loader.py                        # из PostgreSQL
python 01_data_loader.py --source cube          # из работающего Cube API
python 01_data_loader.py --jira-plan plan.xlsx  # с JIRA execution plan
python 02_build_faiss.py                        # FAISS-индекс
```

### 4. Закрытый контур (JupyterLab, без интернета)

```bash
cd closed-env-package
# Отредактируйте config.yml (GreenPlum/Hive/DuckDB + GigaChat прокси)
python validate.py                              # проверка окружения
python 01_data_loader.py                        # генерация моделей
python 02_build_faiss.py                        # FAISS-индекс
# Откройте 03_agent.ipynb в JupyterLab
```

## Поддерживаемые LLM

| Провайдер | Переменная | Где работает |
|-----------|-----------|--------------|
| OpenAI (GPT-4o-mini) | `OPENAI_API_KEY` | Открытый контур |
| GigaChat (Sber) | `GIGACHAT_CREDENTIALS` или прокси `base_url` | Оба контура |

## Поддерживаемые источники данных

| Источник | `database.driver` | Описание |
|----------|-------------------|----------|
| PostgreSQL | `postgresql` | Прямое подключение (psycopg2) |
| GreenPlum | `greenplum` | SQLAlchemy + Kerberos |
| Hive | `hive` | PyHive + Kerberos |
| DuckDB | `duckdb` | Локальный файл (из Parquet/CSV) |
| Cube API | `cube` | Чтение метаданных из работающего Cube |

## Knowledge Base (KB)

Data loader поддерживает внешний YAML-файл с описаниями таблиц вашего домена:

```bash
python 01_data_loader.py --kb ./kb/jira_kb.yml    # для JIRA
python 01_data_loader.py --kb ./kb/finance_kb.yml  # для финансов
python 01_data_loader.py                           # без KB — чистый GigaChat
```

KB файл содержит:
- Русские описания таблиц и колонок
- Рекомендуемые меры (measures) для Cube
- Нечёткое сопоставление имён таблиц (issue_links ↔ issuelink, priorities ↔ priority)

Готовые KB: `kb/jira_kb.yml` (22 таблицы). Шаблон для своего домена: `kb/template_kb.yml`.
Подробности: `closed-env-package/kb/README.md`.

## Конфигурация

Все секреты хранятся в `.env` файлах (не коммитятся).
Шаблоны: `.env.example` в каждой директории.

## Лицензия

MIT
