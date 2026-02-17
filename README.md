# Semantic Layer Agent for JIRA Analytics

AI-агент для аналитики данных через естественный язык. Задаёте вопрос на русском — получаете данные из базы.

**Архитектура:** Вопрос → FAISS (семантический поиск) → LLM (генерация запроса) → Cube.js (выполнение) → Ответ

## Структура проекта

```
├── cube-jira/                  # Cube.js — семантический слой
│   ├── model/cubes/            # YAML-модели данных (issues, users, sprints...)
│   ├── semantic/               # Glossary, examples, конфиг семантического слоя
│   ├── docker-compose.yml      # Запуск Cube в Docker
│   └── .env.example            # Шаблон подключения к БД
│
├── jira-ai-poc/                # AI-агент (основной сервер)
│   ├── agent/                  # Python-агент
│   │   ├── universal_agent.py  # Ядро: FAISS + LLM + Cube API
│   │   ├── prompt_builder.py   # Построение промптов для LLM
│   │   ├── semantic_app.py     # FastAPI веб-интерфейс
│   │   ├── semantic_agent.py   # Базовый агент
│   │   └── .env.example        # Шаблон: OpenAI / GigaChat ключи
│   └── README.md
│
├── closed-env-package/         # Пакет для закрытого контура (без интернета)
│   ├── 00_load_duckdb.py       # Загрузка Parquet/CSV → DuckDB
│   ├── 01_data_loader.py       # Автогенерация Cube-моделей из БД
│   ├── 02_build_faiss.py       # Построение FAISS-индекса
│   ├── 03_agent.ipynb          # Jupyter-ноутбук агента
│   ├── config.yml              # Единая конфигурация
│   ├── validate.py             # Валидация перед деплоем
│   └── cube.env.example        # Шаблон .env для Cube
│
├── jira-api-express/           # Express.js REST API (справочный)
└── vulcan-jira-api/            # VulcanSQL API (справочный, не используется)
```

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
# Заполните .env: OPENAI_API_KEY или GIGACHAT_CREDENTIALS
pip install -r requirements.txt
python semantic_app.py
# Откройте: http://localhost:8000
```

### 3. Закрытый контур (без интернета, JupyterLab)

```bash
cd closed-env-package
# Отредактируйте config.yml
python 00_load_duckdb.py --data-dir ./data     # если DuckDB
python 01_data_loader.py                        # генерация моделей
python 02_build_faiss.py                        # FAISS-индекс
# Откройте 03_agent.ipynb в JupyterLab
```

## Поддерживаемые LLM

| Провайдер | Переменная | Где работает |
|-----------|-----------|--------------|
| OpenAI (GPT-4o-mini) | `OPENAI_API_KEY` | Открытый контур |
| GigaChat (Sber) | `GIGACHAT_CREDENTIALS` или прокси `base_url` | Закрытый контур |

## Поддерживаемые источники данных

| Источник | `database.driver` | Описание |
|----------|-------------------|----------|
| PostgreSQL | `postgresql` | Прямое подключение |
| GreenPlum | `greenplum` | Через psycopg2 (PG-совместимый) |
| DuckDB | `duckdb` | Локальный файл, из Parquet/CSV |
| Cube API | `cube` | Читает метаданные из работающего Cube |

## Конфигурация

Все секреты хранятся в `.env` файлах (не коммитятся).
Шаблоны: `.env.example` в каждой директории.

## Лицензия

MIT
