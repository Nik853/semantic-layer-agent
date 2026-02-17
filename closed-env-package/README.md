# Семантический Агент для Cube — Закрытый контур

Аналитика данных на естественном языке. Задаёте вопрос на русском → агент генерирует запрос к Cube → получаете данные.

## Архитектура

```
Вопрос → FAISS (семантический поиск) → GigaChat (генерация запроса) → Cube (выполнение) → Ответ
```

**Компоненты:**
- **Cube** — семантический слой над PostgreSQL (уже установлен)
- **FAISS** — локальная векторная БД для поиска по метаданным
- **GigaChat** — LLM для генерации Cube-запросов из естественного языка
- **JupyterLab** — интерфейс для работы с агентом

## Структура файлов

```
closed-env-package/
├── config.yml              ← ЗАПОЛНИТЬ: подключения к БД, Cube, GigaChat
├── requirements.txt        ← Зависимости Python
├── 01_data_loader.py       ← Шаг 1: Чтение БД → описания GigaChat → YAML Cube
├── 02_build_faiss.py       ← Шаг 2: Метаданные Cube → FAISS-индекс
├── 03_agent.ipynb          ← Шаг 3: Jupyter-ноутбук для вопросов
├── config/                 ← Создаётся автоматически шагом 1
│   ├── glossary.yml        ← Бизнес-глоссарий (можно редактировать)
│   ├── examples.yml        ← Примеры запросов (можно редактировать)
│   └── semantic_layer.yml  ← Конфигурация
├── cube_models/            ← Создаётся автоматически шагом 1
│   ├── table1.yml          ← YAML-модель для Cube
│   └── ...
└── faiss_index/            ← Создаётся автоматически шагом 2
    ├── index.faiss         ← Векторный индекс
    ├── index.pkl           ← Метаданные
    └── members.json        ← Cube-мемберы
```

## Пошаговая установка

### Шаг 0: Подготовка (один раз)

**Автоматический режим (рекомендуется):**

Все три скрипта (`01_data_loader.py`, `02_build_faiss.py`, `03_agent.ipynb`) автоматически
проверяют наличие зависимостей и устанавливают недостающие при первом запуске.
Просто запустите нужный скрипт — он сам скачает всё необходимое, включая:
- `faiss-cpu` — векторная БД
- `sentence-transformers` + `torch` (CPU) — модель эмбеддингов
- `langchain-gigachat` — клиент GigaChat
- `psycopg2-binary` — PostgreSQL-драйвер

PyTorch устанавливается в CPU-версии (экономия ~2 ГБ по сравнению с CUDA).

**Ручной режим (если нужна предустановка):**
```bash
pip install -r requirements.txt
```

**Закрытый контур (нет интернета):**

На машине с интернетом скачайте пакеты:
```bash
pip download -r requirements.txt -d ./wheels
pip download torch --index-url https://download.pytorch.org/whl/cpu -d ./wheels
```
Скопируйте папку `wheels/` на закрытый сервер:
```bash
pip install --no-index --find-links=./wheels -r requirements.txt
```

**Модель эмбеддингов (закрытый контур):**

На машине с интернетом:
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
model.save("./embedding_model")
```

Скопируйте папку `embedding_model/` на закрытый сервер и в `config.yml` укажите:
```yaml
faiss:
  embedding_model: "./embedding_model"
```

### Шаг 1: Настройка конфигурации

Откройте `config.yml` и заполните:

```yaml
database:
  host: "адрес_сервера_postgresql"
  port: 5432
  name: "имя_базы_данных"
  user: "пользователь"
  password: "пароль"

cube:
  api_url: "http://localhost:4000/cubejs-api/v1"
  api_token: ""              # Если Cube требует токен
  model_path: "./cube_models"

gigachat:
  credentials: "ваш_ключ_gigachat"
  model: "GigaChat"
  verify_ssl: false
```

### Шаг 2: Загрузка данных в Cube

```bash
python 01_data_loader.py
```

**Что делает:**
1. Читает все таблицы из PostgreSQL
2. Для каждой таблицы отправляет структуру + примеры данных в GigaChat
3. GigaChat генерирует русские описания (title, description)
4. Создаёт YAML-модели для Cube в папке `cube_models/`
5. Генерирует `glossary.yml` и `examples.yml`

**После выполнения:**
1. Скопируйте файлы из `cube_models/` в папку `model/cubes/` вашего Cube-проекта
2. Перезапустите Cube:
```bash
npx cubejs-server
```
3. Проверьте что Cube работает:
```bash
curl http://localhost:4000/cubejs-api/v1/meta
```

### Шаг 3: Построение FAISS-индекса

```bash
python 02_build_faiss.py
```

**Что делает:**
1. Загружает метаданные из Cube REST API `/meta`
2. Создаёт эмбеддинги для каждого поля (measure + dimension)
3. Строит FAISS-индекс и сохраняет в `faiss_index/`

### Шаг 4: Работа с агентом

Откройте JupyterLab и ноутбук `03_agent.ipynb`.

1. Выполните первые 3 ячейки (инициализация) — один раз
2. В ячейке "ЗАДАВАЙТЕ ВОПРОСЫ" пишите:

```python
print(ask("Сколько задач по проектам?"))
print(ask("Покажи задачи по проекту AI"))
print(ask("Сколько открытых задач с исполнителем Lisa"))
```

Для отладки используйте `verbose=True`:
```python
print(ask("Ваш вопрос", verbose=True))
```

## Настройка взаимодействия компонентов

### Cube ↔ PostgreSQL
Cube подключается к БД через `.env` файл в его проекте:
```env
CUBEJS_DB_TYPE=postgres
CUBEJS_DB_HOST=localhost
CUBEJS_DB_PORT=5432
CUBEJS_DB_NAME=your_database
CUBEJS_DB_USER=your_user
CUBEJS_DB_PASS=your_password
```

### Agent ↔ Cube
Агент общается с Cube по HTTP REST API. URL указывается в `config.yml → cube.api_url`.
По умолчанию: `http://localhost:4000/cubejs-api/v1`

### Agent ↔ FAISS
FAISS — это локальная библиотека, файлы индекса хранятся на диске.
Путь указывается в `config.yml → faiss.index_path`. Сетевое подключение не нужно.

### Agent ↔ GigaChat
Агент отправляет промпт в GigaChat API и получает JSON-запрос для Cube.
Ключ указывается в `config.yml → gigachat.credentials`.
Если GigaChat доступен через внутренний прокси, убедитесь что `verify_ssl: false`.

## Как улучшить качество ответов

### 1. Отредактируйте glossary.yml
Добавьте бизнес-термины вашей предметной области:
```yaml
клиент:
  aliases: [клиент, клиента, заказчик, customer]
  semantic_type: entity
  fields: ["customers.name"]
  filter_operator: contains
  description: "Клиент компании"
```

### 2. Добавьте примеры в examples.yml
Чем больше примеров — тем лучше LLM генерирует запросы:
```yaml
- question: "сколько клиентов по регионам"
  intent: analytics
  query:
    measures: ["customers.count"]
    dimensions: ["customers.region"]
    limit: 100
  tags: [count, customer, region]
```

### 3. Улучшите описания в Cube-моделях
В YAML-файлах кубов добавляйте подробные `description`:
```yaml
- name: revenue
  sql: revenue
  type: sum
  title: Выручка
  description: >
    Суммарная выручка в рублях. Используйте для анализа
    по клиентам, регионам, периодам
```

### 4. Перестройте FAISS после изменений
После редактирования Cube-моделей:
```bash
# Перезапустите Cube
npx cubejs-server
# Перестройте индекс
python 02_build_faiss.py
```

## Решение проблем

| Проблема | Решение |
|----------|---------|
| `Connection refused` к Cube | Проверьте что Cube запущен: `ps aux \| grep cube` |
| GigaChat timeout | Увеличьте `gigachat.timeout` в config.yml |
| FAISS не находит нужные поля | Улучшите `description` в Cube-моделях и перестройте индекс |
| LLM генерирует неправильный запрос | Добавьте похожий пример в `examples.yml` |
| `No module named 'faiss'` | `pip install faiss-cpu` |
| Модель эмбеддингов не найдена | Скачайте модель и укажите локальный путь в config.yml |
