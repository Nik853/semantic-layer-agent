# Инструменты Cube-JIRA

Скрипты для автоматической генерации и обогащения Cube-моделей.

## Скрипты

| Файл | Назначение |
|------|-----------|
| `01_data_loader.py` | Генерация YAML-моделей Cube из БД + описания через GigaChat |
| `02_build_faiss.py` | Построение FAISS-индекса для семантического поиска по моделям |
| `embedding_utils.py` | Фабрика эмбеддингов (HuggingFace / GigaChat) |
| `db_sources.py` | Подключение к GreenPlum/Hive через SQLAlchemy + Kerberos |
| `kerberos_auth.py` | Утилита создания Kerberos-тикетов |
| `kb/` | Knowledge Base — внешние YAML-файлы с описаниями таблиц |

## Knowledge Base

Data loader использует внешний YAML-файл для обогащения описаний.
KB не привязана к JIRA — можно создать файл для любого домена.

```bash
# Для JIRA:
python 01_data_loader.py --kb ./kb/jira_kb.yml

# Для своего домена:
cp kb/template_kb.yml kb/my_domain.yml
# Заполните описания ваших таблиц
python 01_data_loader.py --kb ./kb/my_domain.yml
```

Подробности формата: `kb/README.md`

## Быстрый старт

```bash
# 1. Настроить config.yml (подключение к БД и GigaChat)

# 2. Сгенерировать модели (без KB — чистый GigaChat):
python 01_data_loader.py

# С Knowledge Base:
python 01_data_loader.py --kb ./kb/jira_kb.yml

# С ETL execution plan:
python 01_data_loader.py --etl-plan sample_execution.xlsx

# Через Cube API (без прямого доступа к БД):
python 01_data_loader.py --source cube

# 3. Построить FAISS-индекс:
python 02_build_faiss.py
```

Модели будут записаны в `../model/cubes/` (рядом с существующими моделями).
