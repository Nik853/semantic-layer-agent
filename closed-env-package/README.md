# Семантический Агент для Cube — Закрытый контур

Аналитика данных на естественном языке. Задаёте вопрос на русском → агент генерирует запрос к Cube → получаете данные.

## Архитектура

```
Вопрос → FAISS (семантический поиск) → GigaChat (генерация запроса) → Cube (выполнение) → Ответ
```

## Структура файлов

```
closed-env-package/
├── config.yml              ← ЗАПОЛНИТЬ: подключения к БД, Cube, GigaChat
├── requirements.txt        ← Зависимости Python
│
├── 01_data_loader.py       ← Шаг 1: БД → GigaChat описания → YAML-модели Cube
├── 02_build_faiss.py       ← Шаг 2: Метаданные Cube → FAISS-индекс
├── 03_agent.ipynb          ← Шаг 3: Jupyter-ноутбук для вопросов
│
├── kb/                     ← Knowledge Base (опционально)
│   ├── jira_kb.yml         ←   Готовая KB для JIRA (22 таблицы)
│   └── template_kb.yml     ←   Шаблон для создания своей KB
│
├── config/                 ← Создаётся автоматически шагом 1
│   ├── glossary.yml        ←   Бизнес-глоссарий
│   ├── examples.yml        ←   Примеры запросов
│   └── semantic_layer.yml  ←   Конфигурация
├── cube_models/            ← Создаётся автоматически шагом 1
│
├── db_sources.py           ← Коннекторы GreenPlum / Hive + Kerberos
├── kerberos_auth.py        ← Утилита Kerberos-аутентификации
├── embedding_utils.py      ← Фабрика эмбеддингов (HuggingFace / GigaChat)
├── 00_load_duckdb.py       ← Вспомогательный: загрузка CSV/Parquet → DuckDB
└── validate.py             ← Валидация окружения
```

## Пошаговая установка

### Шаг 0: Подготовка

Скрипты автоматически устанавливают зависимости при первом запуске.
Для ручной установки: `pip install -r requirements.txt`

**Закрытый контур (нет интернета):**
```bash
# На машине с интернетом:
pip download -r requirements.txt -d ./wheels
pip download torch --index-url https://download.pytorch.org/whl/cpu -d ./wheels

# На закрытом сервере:
pip install --no-index --find-links=./wheels -r requirements.txt
```

### Шаг 1: Настройка config.yml

```yaml
database:
  driver: "postgresql"     # postgresql / greenplum / hive / duckdb / cube
  host: "адрес_сервера"
  port: 5432
  name: "имя_базы"
  user: "пользователь"
  password: "пароль"

cube:
  api_url: "http://localhost:4000/cubejs-api/v1"
  model_path: "./cube_models"

gigachat:
  credentials: "ваш_ключ"   # Вариант 1: SberCloud
  # base_url: "http://..."   # Вариант 2: внутренний прокси
```

### Шаг 2: Генерация моделей

```bash
# Базовая генерация (БД + GigaChat)
python 01_data_loader.py

# С Knowledge Base (лучше описания для известного домена)
python 01_data_loader.py --kb ./kb/jira_kb.yml

# С ETL plan (обогащение из Excel с метаданными ETL-процессов)
python 01_data_loader.py --etl-plan ./plan.xlsx

# Всё вместе
python 01_data_loader.py --kb ./kb/jira_kb.yml --etl-plan ./plan.xlsx
```

**Что делает:**
1. Читает все таблицы из БД
2. Анализирует реальные данные: enum-значения, NULL-статистику, типы
3. GigaChat генерирует русские описания на основе структуры + данных
4. Дополняет описания из KB и ETL plan (если указаны)
5. Создаёт YAML-модели для Cube + glossary + examples

### Шаг 2а: Обогащение уже существующих моделей

Если модели уже сгенерированы и вы получили ETL plan позже:

```bash
# Быстрое обогащение (без GigaChat, только метаданные ETL)
python 01_data_loader.py --enrich-etl --etl-plan ./plan.xlsx

# Полное обогащение (GigaChat переописывает колонки с учётом ETL + данных)
python 01_data_loader.py --enrich-etl --etl-plan ./plan.xlsx --enrich-with-llm

# Указать папку с моделями явно
python 01_data_loader.py --enrich-etl --etl-plan ./plan.xlsx --model-dir ./cube_models
```

**Что делает `--enrich-etl`:**
- Парсит Spark execution plan из ETL файла (исходные таблицы, JOINы, колонки)
- Сопоставляет ETL-записи с существующими Cube-моделями по имени
- Дописывает в description модели: целевую таблицу ETL, источники, связи
- Показывает колонки из ETL, отсутствующие в модели
- С флагом `--enrich-with-llm`: подключается к БД за sample data и просит GigaChat переописать всё с учётом ETL-контекста

### Шаг 3: Построение FAISS-индекса

```bash
python 02_build_faiss.py
```

### Шаг 4: Работа с агентом

Откройте `03_agent.ipynb` в JupyterLab:
```python
print(ask("Сколько задач по проектам?"))
print(ask("Покажи открытые задачи с исполнителем Lisa"))
```

## Knowledge Base (KB)

### Зачем нужна

KB — это **ваши экспертные знания о данных**, оформленные в YAML-файл. Без KB скрипт полагается только на GigaChat, который описывает таблицы по именам колонок и sample data. Это работает, но:

- GigaChat не знает доменную специфику (что `pkey` — это "ключ задачи PROJECT-123")
- GigaChat не знает какие метрики имеют бизнес-смысл (открытые задачи = `resolution IS NULL`)
- GigaChat может вернуть невалидный JSON → описание будет generic fallback

KB решает все три проблемы, давая точные описания и рекомендуемые меры.

### Когда нужна, когда нет

| Ситуация | Нужна KB? |
|----------|-----------|
| Первый раз подключаете неизвестное хранилище | Нет — начните без KB, посмотрите результат |
| Описания GigaChat слишком общие | Да — добавьте column_hints для проблемных таблиц |
| Нужны бизнес-метрики (open/closed count) | Да — добавьте suggested_measures |
| У вас JIRA | Да — используйте готовую `kb/jira_kb.yml` |
| Повторная генерация для того же домена | Да — KB ускоряет и улучшает результат |

### Как создать свою KB

1. Скопируйте шаблон:
```bash
cp kb/template_kb.yml kb/my_domain_kb.yml
```

2. Заполните для ваших таблиц:
```yaml
# Имя паттерна — имя таблицы (или часть имени, без схемы)
orders:
  title: "Заказы"
  description: "Таблица заказов клиентов с суммами и статусами."
  column_hints:
    order_date: "Дата оформления заказа"
    total_amount: "Сумма заказа в рублях"
    status: "Статус: new, processing, shipped, delivered, cancelled"
  suggested_measures:
    - name: total_revenue
      sql: "total_amount"
      type: sum
      title: "Выручка"
      description: "Суммарная выручка по заказам"
    - name: cancelled_count
      sql: "CASE WHEN {CUBE}.status = 'cancelled' THEN 1 END"
      type: count
      title: "Отменённые заказы"
      description: "Количество отменённых заказов"
```

3. Подключите:
```yaml
# config.yml
knowledge_base_path: "./kb/my_domain_kb.yml"
```
или через CLI: `python 01_data_loader.py --kb ./kb/my_domain_kb.yml`

### Что заполнять в KB

| Поле | Обязательно | Описание |
|------|-------------|----------|
| `title` | Да | Русское название таблицы (2-3 слова) |
| `description` | Да | Что хранит таблица (1-2 предложения) |
| `column_hints` | Нет | Описания колонок, которые GigaChat не угадает |
| `suggested_measures` | Нет | Бизнес-метрики с SQL-выражениями для Cube |

Не нужно описывать каждую колонку — только те, где имя неочевидно (pkey, pname, cfname) или есть бизнес-логика (resolution IS NULL = открытая задача).

## ETL Execution Plan

Файл Excel/CSV с метаданными ETL-процессов. Содержит Spark execution plans — скрипт парсит из них:
- Исходные таблицы и колонки
- JOIN-связи между таблицами
- Целевые таблицы и их структуру

Подключение: `--etl-plan ./file.xlsx` или `etl_plan_path` в config.yml

## Решение проблем

| Проблема | Решение |
|----------|---------|
| `Connection refused` к Cube | Проверьте что Cube запущен |
| GigaChat timeout / 429 | Скрипт автоматически делает retry (3 попытки) |
| GigaChat возвращает невалидный JSON | Встроена автокоррекция: запятые, скобки, кавычки |
| Описания слишком общие | Добавьте Knowledge Base или используйте `--enrich-with-llm` |
| FAISS не находит нужные поля | Улучшите description в моделях → перестройте индекс |
| `No module named 'faiss'` | `pip install faiss-cpu` |
