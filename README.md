# Semantic Layer Agent

AI-агент для аналитики данных через естественный язык. Задаёте вопрос на русском — получаете данные из базы.

**Архитектура:** Вопрос → FAISS (семантический поиск) → LLM (генерация запроса) → Cube.js (выполнение) → Ответ

## Структура проекта

```
├── cube-jira/                  # Cube.js — семантический слой
│   ├── model/cubes/            # 81 YAML-модель (автогенерация из БД)
│   ├── semantic/               # Glossary, examples, конфиг
│   ├── tools/                  # Инструменты генерации моделей
│   │   ├── 01_data_loader.py   #   БД → GigaChat → YAML-модели Cube
│   │   ├── 02_build_faiss.py   #   Построение FAISS-индекса
│   │   ├── kb/                 #   Knowledge Base файлы
│   │   └── config.yml          #   Конфигурация
│   ├── docker-compose.yml      # Запуск Cube в Docker
│   └── .env.example            # Шаблон подключения к БД
│
├── jira-ai-poc/                # AI-агент (FastAPI веб-сервер)
│   └── agent/
│       ├── universal_agent.py  # Ядро: FAISS + LLM + Cube API
│       ├── semantic_app.py     # FastAPI (http://localhost:8000)
│       └── .env.example        # Шаблон ключей LLM
│
└── closed-env-package/         # Пакет для закрытого контура (JupyterLab)
    ├── 01_data_loader.py       # Генерация моделей + --enrich-etl
    ├── 02_build_faiss.py       # FAISS-индекс
    ├── 03_agent.ipynb          # Jupyter-ноутбук агента
    ├── kb/                     # Knowledge Base файлы
    └── config.yml              # Конфигурация
```

## Быстрый старт

### 1. Cube.js (семантический слой)

```bash
cd cube-jira
cp .env.example .env       # заполнить хост, БД, пользователь, пароль
npm install && docker-compose up -d
```

### 2. Генерация моделей из БД

```bash
cd cube-jira/tools         # или closed-env-package/
vim config.yml             # заполнить БД + GigaChat

python 01_data_loader.py                              # базовая генерация
python 01_data_loader.py --kb ./kb/jira_kb.yml        # + Knowledge Base
python 01_data_loader.py --etl-plan plan.xlsx         # + ETL plan
python 01_data_loader.py --enrich-etl --etl-plan plan.xlsx  # обогатить готовые модели
```

### 3. AI-агент

```bash
cd jira-ai-poc/agent
cp .env.example .env       # заполнить OPENAI_API_KEY или GIGACHAT_CREDENTIALS
pip install -r requirements.txt && python semantic_app.py
```

### 4. Закрытый контур (JupyterLab)

```bash
cd closed-env-package
vim config.yml             # GreenPlum/Hive/DuckDB + GigaChat прокси
python 01_data_loader.py && python 02_build_faiss.py
# Открыть 03_agent.ipynb в JupyterLab
```

## Data Loader — режимы работы

### Полная генерация (с нуля)

```bash
python 01_data_loader.py [--kb FILE] [--etl-plan FILE] [--source TYPE]
```

1. Читает все таблицы из БД
2. Анализирует sample data: enum-значения, NULL-статистику, единицы измерения
3. GigaChat описывает каждую таблицу и колонку на русском
4. Дополняет из KB (если указана) и ETL plan (если указан)
5. Создаёт YAML-модели + glossary + examples

### Обогащение существующих моделей (`--enrich-etl`)

```bash
python 01_data_loader.py --enrich-etl --etl-plan plan.xlsx [--enrich-with-llm] [--model-dir DIR]
```

Обновляет уже сгенерированные YAML-модели **без перегенерации**:
- Парсит Spark execution plan: исходные таблицы, JOINы, колонки, фильтры
- Дописывает ETL-контекст в description моделей
- С `--enrich-with-llm`: GigaChat переописывает колонки с учётом ETL + sample data

## Knowledge Base (KB)

**Что это:** YAML-файл с вашими экспертными знаниями о данных — описания таблиц, подсказки по колонкам, бизнес-метрики.

**Зачем:** GigaChat описывает таблицы по именам колонок и примерам данных. Но он не знает, что `pkey` — это ключ задачи `PROJECT-123`, а `resolution IS NULL` означает открытую задачу. KB даёт эти знания.

**Когда нужна:**
- Имена колонок неочевидны (`pname`, `cfname`, `pkey`)
- Нужны бизнес-метрики (`open_count`, `resolved_count`)
- Хотите стабильно хорошие описания независимо от GigaChat

**Когда не нужна:**
- Первый запуск на неизвестных данных — начните без KB, посмотрите результат
- Имена колонок понятные (`status`, `created_at`, `user_name`)

**Как создать:**

```bash
cp kb/template_kb.yml kb/my_domain.yml
```

```yaml
orders:
  title: "Заказы"
  description: "Таблица заказов клиентов."
  column_hints:
    total_amount: "Сумма заказа в рублях"
    status: "Статус: new, processing, shipped, delivered, cancelled"
  suggested_measures:
    - name: total_revenue
      sql: "total_amount"
      type: sum
      title: "Выручка"
      description: "Суммарная выручка"
```

Готовые KB: `kb/jira_kb.yml` (22 таблицы JIRA). Подробности: `closed-env-package/kb/README.md`.

## Поддерживаемые источники данных

| Источник | `database.driver` | Описание |
|----------|-------------------|----------|
| PostgreSQL | `postgresql` | Прямое подключение (psycopg2) |
| GreenPlum | `greenplum` | SQLAlchemy + Kerberos |
| Hive | `hive` | PyHive + Kerberos |
| DuckDB | `duckdb` | Локальный файл (из Parquet/CSV) |
| Cube API | `cube` | Чтение метаданных из работающего Cube |

## Поддерживаемые LLM

| Провайдер | Переменная | Где работает |
|-----------|-----------|--------------|
| OpenAI (GPT-4o-mini) | `OPENAI_API_KEY` | Открытый контур |
| GigaChat (Sber) | `credentials` или `base_url` прокси | Оба контура |

## Лицензия

MIT
