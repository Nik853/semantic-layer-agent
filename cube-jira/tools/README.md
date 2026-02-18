# Инструменты Cube-JIRA

Скрипты для автоматической генерации и обогащения Cube-моделей.

## Скрипты

| Файл | Назначение |
|------|-----------|
| `01_data_loader.py` | Генерация YAML-моделей Cube из БД + описания через GigaChat + JIRA Knowledge Base |
| `02_build_faiss.py` | Построение FAISS-индекса для семантического поиска по моделям |
| `embedding_utils.py` | Фабрика эмбеддингов (HuggingFace / GigaChat) |
| `db_sources.py` | Подключение к GreenPlum/Hive через SQLAlchemy + Kerberos |
| `kerberos_auth.py` | Утилита создания Kerberos-тикетов |

## Быстрый старт

```bash
# 1. Настроить config.yml (подключение к БД и GigaChat)
# 2. Сгенерировать модели:
python 01_data_loader.py

# С JIRA execution plan:
python 01_data_loader.py --jira-plan sample_execution.xlsx

# Через Cube API (без прямого доступа к БД):
python 01_data_loader.py --source cube

# 3. Построить FAISS-индекс:
python 02_build_faiss.py
```

Модели будут записаны в `../model/cubes/` (рядом с существующими моделями).
