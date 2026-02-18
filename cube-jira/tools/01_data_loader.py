"""
=================================================================
ЗАГРУЗЧИК ДАННЫХ В CUBE
=================================================================
Скрипт читает структуру данных, генерирует описания
на русском языке через GigaChat и создаёт YAML-модели для Cube.

Поддерживает режимы источника данных (database.driver в config.yml):
  - postgresql              — прямое подключение (psycopg2)
  - greenplum               — Greenplum через SQLAlchemy (Kerberos опционально)
  - hive                    — Hive через SQLAlchemy/PyHive (Kerberos)
  - duckdb                  — локальный DuckDB-файл
  - cube                    — чтение из работающего Cube API (без БД)

Дополнительно:
  --jira-plan <file.xlsx>   — обогатить модели из JIRA execution plan файла

Запуск: python 01_data_loader.py
        python 01_data_loader.py --source cube
        python 01_data_loader.py --source duckdb
        python 01_data_loader.py --jira-plan sample_execution.xlsx
=================================================================
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

# ============================================================
# Автоустановка зависимостей
# ============================================================

def _ensure_packages():
    """Проверить и установить недостающие пакеты (базовые)"""
    required = {
        "yaml": "pyyaml",
        "langchain_gigachat": "langchain-gigachat",
    }
    missing = []
    for module, pip_name in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print(f"📦 Установка недостающих пакетов: {', '.join(missing)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + missing
        )
        print("✅ Пакеты установлены")

_ensure_packages()

import yaml

# psycopg2 / duckdb подгружаются по необходимости в create_data_source()
try:
    import psycopg2
except ImportError:
    psycopg2 = None  # Не нужен для duckdb/cube режимов

# ============================================================
# Загрузка конфигурации
# ============================================================

def load_config(config_path="config.yml"):
    """Загрузить конфигурацию из YAML-файла"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ============================================================
# Подключение к GigaChat
# ============================================================

def create_gigachat(config):
    """Создать клиент GigaChat. Поддерживает 2 режима:
       1. credentials — прямой доступ (SberCloud)
       2. base_url + access_token — через прокси (закрытый контур)
    """
    from langchain_gigachat import GigaChat
    
    gc = config["gigachat"]
    model = gc.get("model", "GigaChat")
    
    # Режим 2: через прокси (base_url + access_token из env)
    if gc.get("base_url"):
        token_env = gc.get("access_token_env", "JPY_API_TOKEN")
        token = os.getenv(token_env, "")
        return GigaChat(
            base_url=gc["base_url"],
            access_token=token,
            model=model,
            timeout=gc.get("timeout", 60)
        )
    
    # Режим 1: через credentials
    if gc.get("credentials"):
        return GigaChat(
            credentials=gc["credentials"],
            model=model,
            verify_ssl_certs=gc.get("verify_ssl", False),
            timeout=gc.get("timeout", 60)
        )
    
    print("❌ Ошибка: Заполните gigachat.credentials или gigachat.base_url в config.yml")
    sys.exit(1)


# ============================================================
# Чтение структуры БД
# ============================================================

def get_db_connection(config):
    """Подключиться к PostgreSQL / GreenPlum"""
    if psycopg2 is None:
        print("❌ psycopg2 не установлен. Установите: pip install psycopg2-binary")
        print("   Или используйте --source duckdb / --source cube")
        sys.exit(1)
    db = config["database"]
    return psycopg2.connect(
        host=db["host"],
        port=db["port"],
        dbname=db["name"],
        user=db["user"],
        password=db["password"]
    )


def get_schema(config):
    """Получить имя схемы из конфига"""
    return config.get("database", {}).get("schema", "public")


def get_tables(conn, schema="public"):
    """Получить список таблиц"""
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = %s 
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """, (schema,))
    tables = [row[0] for row in cur.fetchall()]
    cur.close()
    return tables


def get_columns(conn, table_name, schema="public"):
    """Получить колонки таблицы с типами"""
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default,
               character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (schema, table_name))
    columns = []
    for row in cur.fetchall():
        columns.append({
            "name": row[0],
            "data_type": row[1],
            "nullable": row[2] == "YES",
            "default": row[3],
            "max_length": row[4]
        })
    cur.close()
    return columns


def get_foreign_keys(conn, table_name, schema="public"):
    """Получить внешние ключи таблицы"""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            kcu.column_name,
            ccu.table_name AS foreign_table,
            ccu.column_name AS foreign_column
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_name = %s
          AND tc.table_schema = %s
    """, (table_name, schema))
    fks = []
    for row in cur.fetchall():
        fks.append({
            "column": row[0],
            "foreign_table": row[1],
            "foreign_column": row[2]
        })
    cur.close()
    return fks


def get_primary_key(conn, table_name, schema="public"):
    """Получить primary key таблицы"""
    cur = conn.cursor()
    cur.execute("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_name = %s
          AND tc.table_schema = %s
    """, (table_name, schema))
    result = cur.fetchone()
    cur.close()
    return result[0] if result else "id"


def get_sample_data(conn, table_name, schema="public", limit=5):
    """Получить примеры данных из таблицы"""
    cur = conn.cursor()
    try:
        cur.execute(f'SELECT * FROM {schema}."{table_name}" LIMIT %s', (limit,))
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
        return columns, rows
    except Exception:
        cur.close()
        return [], []


def get_row_count(conn, table_name, schema="public"):
    """Получить количество строк"""
    cur = conn.cursor()
    cur.execute(f'SELECT COUNT(*) FROM {schema}."{table_name}"')
    count = cur.fetchone()[0]
    cur.close()
    return count


# ============================================================
# Чтение структуры из DuckDB
# ============================================================

class DuckDBSource:
    """Источник данных — локальный DuckDB-файл.
    Реализует тот же интерфейс что и psycopg2-функции выше.
    """

    def __init__(self, config):
        import duckdb
        db_path = config["database"].get("path", "./data.duckdb")
        self.schema = config["database"].get("schema", "main")
        self.conn = duckdb.connect(db_path, read_only=True)
        print(f"✅ DuckDB: {db_path} (schema={self.schema})")

    def get_tables(self):
        rows = self.conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = ? AND table_type = 'BASE TABLE' "
            "ORDER BY table_name",
            [self.schema]
        ).fetchall()
        return [r[0] for r in rows]

    def get_columns(self, table_name):
        rows = self.conn.execute(
            "SELECT column_name, data_type, is_nullable, column_default, "
            "character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? "
            "ORDER BY ordinal_position",
            [self.schema, table_name]
        ).fetchall()
        return [{
            "name": r[0],
            "data_type": r[1],
            "nullable": r[2] == "YES",
            "default": r[3],
            "max_length": r[4]
        } for r in rows]

    def get_foreign_keys(self, table_name):
        # DuckDB поддерживает FK, но не всегда заполняет information_schema
        try:
            rows = self.conn.execute(
                "SELECT kcu.column_name, ccu.table_name, ccu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON ccu.constraint_name = tc.constraint_name "
                "WHERE tc.constraint_type = 'FOREIGN KEY' "
                "  AND tc.table_name = ? AND tc.table_schema = ?",
                [table_name, self.schema]
            ).fetchall()
            return [{"column": r[0], "foreign_table": r[1], "foreign_column": r[2]}
                    for r in rows]
        except Exception:
            return []

    def get_primary_key(self, table_name):
        try:
            rows = self.conn.execute(
                "SELECT kcu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                "WHERE tc.constraint_type = 'PRIMARY KEY' "
                "  AND tc.table_name = ? AND tc.table_schema = ?",
                [table_name, self.schema]
            ).fetchall()
            return rows[0][0] if rows else "id"
        except Exception:
            return "id"

    def get_sample_data(self, table_name, limit=5):
        try:
            result = self.conn.execute(
                f'SELECT * FROM {self.schema}."{table_name}" LIMIT ?', [limit]
            )
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return columns, rows
        except Exception:
            return [], []

    def get_row_count(self, table_name):
        result = self.conn.execute(
            f'SELECT COUNT(*) FROM {self.schema}."{table_name}"'
        )
        return result.fetchone()[0]

    def close(self):
        self.conn.close()


# ============================================================
# Чтение метаданных из работающего Cube API
# ============================================================

class CubeAPISource:
    """Источник данных — метаданные из Cube REST API /meta.
    Не требует подключения к БД вообще.
    Cube уже работает → читаем его структуру.
    """

    def __init__(self, config):
        import httpx
        self.cube_url = config["cube"]["api_url"]
        self.schema = config["database"].get("schema", "public")
        headers = {}
        token = config["cube"].get("api_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        resp = httpx.get(f"{self.cube_url}/meta", headers=headers, timeout=15.0)
        resp.raise_for_status()
        self.meta = resp.json()
        self.cubes = {c["name"]: c for c in self.meta.get("cubes", [])}
        print(f"✅ Cube API: {len(self.cubes)} кубов загружено из {self.cube_url}")

    def get_tables(self):
        return sorted(self.cubes.keys())

    def get_columns(self, table_name):
        cube = self.cubes.get(table_name, {})
        columns = []
        for dim in cube.get("dimensions", []):
            short_name = dim["name"].split(".")[-1]
            columns.append({
                "name": short_name,
                "data_type": dim.get("type", "string"),
                "nullable": True,
                "default": None,
                "max_length": None
            })
        return columns

    def get_foreign_keys(self, table_name):
        # Cube API не отдаёт FK — joins обнаружим по именам колонок
        return []

    def get_primary_key(self, table_name):
        cube = self.cubes.get(table_name, {})
        for dim in cube.get("dimensions", []):
            if dim.get("primaryKey"):
                return dim["name"].split(".")[-1]
        return "id"

    def get_sample_data(self, table_name, limit=5):
        # Не можем получить sample data через Cube API
        return [], []

    def get_row_count(self, table_name):
        # Пробуем count из Cube
        import httpx
        cube = self.cubes.get(table_name, {})
        count_measure = None
        for m in cube.get("measures", []):
            if m.get("type") == "count":
                count_measure = m["name"]
                break
        if not count_measure:
            return 0
        try:
            headers = {"Content-Type": "application/json"}
            resp = httpx.post(
                f"{self.cube_url}/load",
                json={"query": {"measures": [count_measure], "limit": 1}},
                headers=headers,
                timeout=15.0
            )
            data = resp.json().get("data", [])
            if data:
                return list(data[0].values())[0]
        except Exception:
            pass
        return 0

    def close(self):
        pass


# ============================================================
# Фабрика: выбор источника данных
# ============================================================

def create_data_source(config, override_source=None):
    """Создать источник данных на основе config.yml или --source аргумента.
    Возвращает объект с методами: get_tables, get_columns, get_foreign_keys,
    get_primary_key, get_sample_data, get_row_count, close.
    """
    driver = override_source or config.get("database", {}).get("driver", "postgresql")
    driver = driver.lower().strip()

    if driver == "duckdb":
        return DuckDBSource(config), driver
    elif driver == "cube":
        return CubeAPISource(config), driver
    elif driver in ("postgresql", "postgres"):
        conn = get_db_connection(config)
        schema = get_schema(config)
        return _PsycopgSource(conn, schema), driver
    elif driver == "greenplum":
        from db_sources import GreenplumSource
        return GreenplumSource(config), driver
    elif driver == "hive":
        from db_sources import HiveSource
        return HiveSource(config), driver
    else:
        print(f"❌ Неизвестный driver: {driver}")
        print("   Допустимые: postgresql, greenplum, hive, duckdb, cube")
        sys.exit(1)


class _PsycopgSource:
    """Обёртка над psycopg2 для единого интерфейса."""
    def __init__(self, conn, schema):
        self.conn = conn
        self.schema = schema

    def get_tables(self):
        return get_tables(self.conn, self.schema)

    def get_columns(self, table_name):
        return get_columns(self.conn, table_name, self.schema)

    def get_foreign_keys(self, table_name):
        return get_foreign_keys(self.conn, table_name, self.schema)

    def get_primary_key(self, table_name):
        return get_primary_key(self.conn, table_name, self.schema)

    def get_sample_data(self, table_name, limit=5):
        return get_sample_data(self.conn, table_name, self.schema, limit)

    def get_row_count(self, table_name):
        return get_row_count(self.conn, table_name, self.schema)

    def close(self):
        self.conn.close()


# ============================================================
# JIRA Knowledge Base — улучшение описаний для JIRA-таблиц
# ============================================================

JIRA_TABLE_HINTS = {
    "jiraissue": {
        "title": "Задачи JIRA",
        "description": "Основная таблица задач JIRA. Содержит все issues с ключами, описаниями, статусами и датами.",
        "suggested_measures": [
            {"name": "open_count", "sql": "CASE WHEN {CUBE}.resolution IS NULL THEN 1 END",
             "type": "count", "title": "Открытые задачи", "description": "Количество нерешённых задач"},
            {"name": "resolved_count", "sql": "CASE WHEN {CUBE}.resolution IS NOT NULL THEN 1 END",
             "type": "count", "title": "Закрытые задачи", "description": "Количество решённых задач"},
        ],
        "column_hints": {
            "pkey": "Ключ задачи (PROJECT-123)",
            "summary": "Заголовок задачи",
            "description": "Подробное описание",
            "created": "Дата создания задачи",
            "updated": "Дата последнего обновления",
            "resolutiondate": "Дата решения задачи",
            "duedate": "Плановый срок выполнения",
            "reporter": "Автор задачи (ID пользователя)",
            "assignee": "Исполнитель задачи (ID пользователя)",
            "priority": "Приоритет (ID)",
            "issuestatus": "Статус задачи (ID)",
            "issuetype": "Тип задачи (ID)",
            "project": "Проект (ID)",
            "resolution": "Резолюция (ID). NULL = задача открыта",
            "story_points": "Оценка сложности в Story Points",
            "timeoriginalestimate": "Первоначальная оценка времени (секунды)",
            "timeestimate": "Текущая оценка времени (секунды)",
            "timespent": "Затраченное время (секунды)",
        },
    },
    "issuestatus": {
        "title": "Статусы задач",
        "description": "Справочник статусов JIRA (Open, In Progress, Done и т.д.)",
        "column_hints": {
            "pname": "Название статуса",
            "description": "Описание статуса",
            "statuscategory": "Категория (todo/in_progress/done)",
        },
    },
    "issuelink": {
        "title": "Связи между задачами",
        "description": "Связи между задачами JIRA (blocks, is blocked by, duplicates, relates to и др.)",
        "suggested_measures": [
            {"name": "link_count", "type": "count", "title": "Количество связей",
             "description": "Общее число связей между задачами"},
        ],
        "column_hints": {
            "source": "ID задачи-источника связи",
            "destination": "ID задачи-назначения связи",
            "linktype": "Тип связи (ID из issuelinktype)",
        },
    },
    "nodeassociation": {
        "title": "Привязки сущностей",
        "description": "Связи между узлами JIRA: задача↔компонент, задача↔версия, проект↔категория и др.",
        "column_hints": {
            "source_node_id": "ID исходной сущности (обычно задачи)",
            "source_node_entity": "Тип исходной сущности (Issue)",
            "sink_node_id": "ID целевой сущности (компонент, версия)",
            "sink_node_entity": "Тип целевой сущности (Component, Version)",
            "association_type": "Тип привязки",
        },
    },
    "project": {
        "title": "Проекты JIRA",
        "description": "Список проектов с ключами, названиями и руководителями.",
        "column_hints": {
            "pkey": "Уникальный ключ проекта (AUTH, PAY, CRM)",
            "pname": "Название проекта",
            "lead": "Руководитель проекта (ID пользователя)",
            "description": "Описание проекта",
            "projecttype": "Тип проекта (software, business)",
        },
    },
    "issuetype": {
        "title": "Типы задач",
        "description": "Справочник типов задач (Bug, Story, Task, Epic и т.д.)",
        "column_hints": {
            "pname": "Название типа задачи",
            "description": "Описание типа",
        },
    },
    "priority": {
        "title": "Приоритеты задач",
        "description": "Справочник приоритетов (Blocker, Critical, High, Medium, Low, Trivial).",
        "column_hints": {
            "pname": "Название приоритета",
            "description": "Описание приоритета",
            "sequence": "Порядковый номер (чем меньше, тем приоритетнее)",
        },
    },
    "resolution": {
        "title": "Резолюции задач",
        "description": "Справочник резолюций (Fixed, Won't Fix, Duplicate, Cannot Reproduce и др.)",
        "column_hints": {
            "pname": "Название резолюции",
            "description": "Описание резолюции",
        },
    },
    "cwd_user": {
        "title": "Пользователи JIRA",
        "description": "Пользователи системы JIRA с логинами и именами.",
        "column_hints": {
            "user_name": "Логин пользователя",
            "display_name": "Отображаемое имя (ФИО)",
            "email_address": "E-mail пользователя",
            "active": "Активен ли пользователь",
        },
    },
    "component": {
        "title": "Компоненты проектов",
        "description": "Компоненты (модули) проектов для категоризации задач.",
        "column_hints": {
            "cname": "Название компонента",
            "description": "Описание компонента",
            "project": "ID проекта",
            "lead": "Ответственный за компонент (ID пользователя)",
        },
    },
    "projectversion": {
        "title": "Версии проектов",
        "description": "Версии (релизы) проектов — для планирования и отслеживания.",
        "column_hints": {
            "vname": "Название версии (1.0, 2.0-RC1)",
            "description": "Описание версии",
            "startdate": "Дата начала версии",
            "releasedate": "Дата релиза",
            "released": "Флаг: версия выпущена",
            "archived": "Флаг: версия архивирована",
            "project": "ID проекта",
        },
    },
    "worklog": {
        "title": "Учёт рабочего времени",
        "description": "Записи логирования рабочего времени по задачам.",
        "suggested_measures": [
            {"name": "total_time_spent", "sql": "timeworked", "type": "sum",
             "title": "Суммарное время (секунды)", "description": "Общее затраченное время"},
        ],
        "column_hints": {
            "issueid": "ID задачи",
            "author": "Автор записи (ID пользователя)",
            "timeworked": "Затраченное время (секунды)",
            "startdate": "Дата начала работы",
            "created": "Дата создания записи",
        },
    },
    "changegroup": {
        "title": "Группы изменений",
        "description": "Группы изменений полей задач (история). Каждая группа = один акт редактирования.",
        "column_hints": {
            "issueid": "ID задачи",
            "author": "Автор изменения (ID пользователя)",
            "created": "Дата изменения",
        },
    },
    "changeitem": {
        "title": "Элементы изменений",
        "description": "Детали каждого изменения: какое поле, старое и новое значение.",
        "column_hints": {
            "groupid": "ID группы изменений (changegroup)",
            "field": "Название изменённого поля (status, assignee, priority...)",
            "oldvalue": "Старое значение (ID)",
            "oldstring": "Старое значение (текст)",
            "newvalue": "Новое значение (ID)",
            "newstring": "Новое значение (текст)",
            "fieldtype": "Тип поля (jira, custom)",
        },
    },
    "customfield": {
        "title": "Кастомные поля",
        "description": "Определения пользовательских полей JIRA.",
        "column_hints": {
            "cfname": "Название поля",
            "customfieldtypekey": "Тип поля (строка, число, дата...)",
            "description": "Описание поля",
        },
    },
    "customfieldvalue": {
        "title": "Значения кастомных полей",
        "description": "Значения пользовательских полей для задач.",
        "column_hints": {
            "issue": "ID задачи",
            "customfield": "ID кастомного поля",
            "stringvalue": "Строковое значение",
            "numbervalue": "Числовое значение",
            "textvalue": "Текстовое значение (большой текст)",
            "datevalue": "Значение даты",
        },
    },
    "issuelinktype": {
        "title": "Типы связей задач",
        "description": "Справочник типов связей (Blocks, Is blocked by, Duplicates и т.д.)",
        "column_hints": {
            "linkname": "Название связи (направление вперёд)",
            "inward": "Описание связи (обратное направление)",
            "outward": "Описание связи (прямое направление)",
        },
    },
    "label": {
        "title": "Метки задач",
        "description": "Метки (label) задач для произвольной категоризации.",
        "column_hints": {
            "issue": "ID задачи",
            "label": "Текст метки",
        },
    },
    "sprint": {
        "title": "Спринты",
        "description": "Спринты Agile-досок — итерации разработки.",
        "column_hints": {
            "name": "Название спринта",
            "start_date": "Дата начала спринта",
            "end_date": "Дата окончания спринта",
            "complete_date": "Дата фактического завершения",
            "state": "Состояние (active, closed, future)",
        },
    },
    "issue_history": {
        "title": "История изменений задач",
        "description": "Журнал изменений полей задач: смены статуса, исполнителя, приоритета и др.",
        "suggested_measures": [
            {"name": "status_change_count",
             "sql": "CASE WHEN {CUBE}.field = 'status' THEN 1 END",
             "type": "count", "title": "Смены статуса",
             "description": "Количество смен статуса задач"},
        ],
        "column_hints": {
            "issue_id": "ID задачи",
            "author_id": "Автор изменения (ID пользователя)",
            "field": "Название изменённого поля (status, assignee, priority...)",
            "old_value": "Старое значение",
            "new_value": "Новое значение",
            "created_at": "Дата изменения",
        },
    },
    "issue_comment": {
        "title": "Комментарии к задачам",
        "description": "Комментарии пользователей к задачам JIRA.",
        "column_hints": {
            "issue_id": "ID задачи",
            "author_id": "Автор комментария (ID пользователя)",
            "body": "Текст комментария",
            "created_at": "Дата создания комментария",
            "updated_at": "Дата обновления комментария",
        },
    },
    "user": {
        "title": "Пользователи JIRA",
        "description": "Пользователи системы JIRA с логинами, именами и ролями.",
        "column_hints": {
            "username": "Логин пользователя",
            "display_name": "Отображаемое имя (ФИО)",
            "email": "E-mail пользователя",
            "is_active": "Активен ли пользователь",
        },
    },
}


def load_jira_plan(plan_path: str) -> dict:
    """Загрузить JIRA execution plan файл (xlsx/csv).
    Возвращает dict: source_table_name → {columns from plan}.
    """
    info = {}
    plan_path_lower = plan_path.lower()

    try:
        if plan_path_lower.endswith(".xlsx") or plan_path_lower.endswith(".xls"):
            import openpyxl
            wb = openpyxl.load_workbook(plan_path, data_only=True)
            ws = wb.active
            headers = [str(c.value or "").strip().lower() for c in ws[1]]
            for row in ws.iter_rows(min_row=2, values_only=True):
                rec = dict(zip(headers, row))
                src_table = str(rec.get("source_table", "") or "").strip()
                if src_table:
                    info[src_table] = {
                        "source_schema": str(rec.get("source_schema", "") or ""),
                        "source_cluster": str(rec.get("source_cluster", "") or ""),
                        "target_table": str(rec.get("table_step2", "") or ""),
                        "process_description": str(rec.get("process_description", "") or "")[:500],
                        "last_updated": str(rec.get("last_updated_time", "") or ""),
                    }
        elif plan_path_lower.endswith(".csv"):
            import csv
            with open(plan_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for rec in reader:
                    src_table = rec.get("source_table", "").strip()
                    if src_table:
                        info[src_table] = {
                            "source_schema": rec.get("source_schema", ""),
                            "source_cluster": rec.get("source_cluster", ""),
                            "target_table": rec.get("table_step2", ""),
                            "process_description": rec.get("process_description", "")[:500],
                            "last_updated": rec.get("last_updated_time", ""),
                        }
        else:
            print(f"⚠️  Неподдерживаемый формат: {plan_path}. Используйте .xlsx или .csv")
            return {}

        print(f"✅ JIRA plan загружен: {len(info)} source-таблиц из {plan_path}")
        for t in info:
            print(f"   - {t}")
        return info

    except Exception as e:
        print(f"⚠️  Ошибка загрузки JIRA plan: {e}")
        return {}


def _singularize(word: str) -> set:
    """Вернуть множество возможных единственных форм для английского слова."""
    forms = {word}
    if word.endswith("ies") and len(word) > 4:
        forms.add(word[:-3] + "y")          # priorities → priority
    if word.endswith("ses") or word.endswith("xes"):
        forms.add(word[:-2])                # statuses → status
    if word.endswith("es") and len(word) > 3:
        forms.add(word[:-2])                # statuses → status
    if word.endswith("s") and not word.endswith("ss"):
        forms.add(word[:-1])                # issues → issue
    return forms


def match_jira_hints(table_name: str, jira_plan: dict = None) -> dict:
    """Найти подсказки из JIRA Knowledge Base для таблицы.
    Сопоставление учитывает подчёркивания (issue_links ↔ issuelink),
    множественное число (priorities ↔ priority), префиксы (jiraissue ↔ issues).
    """
    tl = table_name.lower()
    tl_no_sep = tl.replace("_", "").replace("-", "")
    tl_singulars = _singularize(tl_no_sep)

    for pattern, hints in JIRA_TABLE_HINTS.items():
        pat_no_sep = pattern.replace("_", "")
        pat_singulars = _singularize(pat_no_sep)

        # 1. Точное совпадение (с нормализацией разделителей + числа)
        if pat_no_sep == tl_no_sep:
            return hints
        if tl_singulars & pat_singulars:
            return hints

        # 2. Префикс "jira" в KB: jiraissue → issue ↔ issues
        if pat_no_sep.startswith("jira"):
            core = pat_no_sep[4:]
            core_singulars = _singularize(core)
            if tl_singulars & core_singulars:
                return hints

        # 3. Префикс "project" в KB: projectversion → version ↔ versions
        if pat_no_sep.startswith("project"):
            core = pat_no_sep[7:]
            core_singulars = _singularize(core)
            if tl_singulars & core_singulars:
                return hints

        # 4. Суффиксный матч: dm_jira_components → component
        for pf in pat_singulars:
            if len(pf) >= 5 and any(tf.endswith(pf) for tf in tl_singulars):
                return hints

        # 5. Подстрока >= 6 символов (избегает ложных матчей)
        for pf in pat_singulars:
            if len(pf) >= 6 and pf in tl_no_sep:
                return hints

    if jira_plan:
        for src_table, plan_info in jira_plan.items():
            src_no_sep = src_table.lower().replace("_", "")
            src_singulars = _singularize(src_no_sep)
            if tl_singulars & src_singulars:
                return {
                    "title": f"Таблица из JIRA ({src_table})",
                    "description": f"Источник: {plan_info.get('source_schema', '')}.{src_table}. "
                                   f"Целевая: {plan_info.get('target_table', '')}.",
                }

    return {}


def enrich_descriptions_with_jira(descriptions: dict, table_name: str,
                                   columns: list, jira_plan: dict = None) -> dict:
    """Дополнить GigaChat-описания подсказками из JIRA Knowledge Base."""
    hints = match_jira_hints(table_name, jira_plan)
    if not hints:
        return descriptions

    col_descs = descriptions.get("columns", {})
    col_hints = hints.get("column_hints", {})

    for col_name, hint_text in col_hints.items():
        if col_name in col_descs:
            existing = col_descs[col_name]
            if not existing.get("description") or len(existing["description"]) < 10:
                existing["description"] = hint_text
        else:
            for c in columns:
                if c["name"].lower() == col_name or col_name in c["name"].lower():
                    col_descs[c["name"]] = col_descs.get(c["name"], {})
                    if not col_descs[c["name"]].get("description"):
                        col_descs[c["name"]]["description"] = hint_text
                    break

    descriptions["columns"] = col_descs
    return descriptions


def get_jira_suggested_measures(table_name: str) -> list:
    """Получить дополнительные меры из JIRA Knowledge Base."""
    hints = match_jira_hints(table_name)
    return hints.get("suggested_measures", [])


# ============================================================
# Обнаружение связей между таблицами
# ============================================================

def detect_implicit_relationships(table_name, columns, all_tables, explicit_fks):
    """
    Найти неявные связи по соглашению об именах (*_id → таблица).
    Обрабатывает:
      - Прямое совпадение: project_id → projects
      - Множественное число: priority_id → priorities, status_id → statuses
      - Префиксы доменных таблиц: status_id → issue_statuses, type_id → issue_types
      - Семантические маппинги: assignee_id → users, reporter_id → users, author_id → users
    """
    explicit_cols = {fk["column"] for fk in explicit_fks}
    implicit = []

    # Семантические маппинги: колонка → целевая таблица
    SEMANTIC_MAP = {
        "assignee": "users",
        "reporter": "users",
        "author": "users",
        "creator": "users",
        "owner": "users",
        "updated_by": "users",
        "created_by": "users",
        "lead": "users",
        "manager": "users",
        "parent": None,  # self-join обрабатывается отдельно
    }

    for col in columns:
        col_name = col["name"]
        if not col_name.endswith("_id") or col_name in explicit_cols:
            continue
        if col_name == "id":
            continue

        base = col_name[:-3]  # "project_id" → "project"

        # 1. Семантический маппинг
        if base in SEMANTIC_MAP:
            target = SEMANTIC_MAP[base]
            if target and target in all_tables:
                implicit.append({
                    "column": col_name,
                    "foreign_table": target,
                    "foreign_column": "id",
                    "source": "implicit"
                })
                continue
            elif target is None and table_name in all_tables:
                # self-join (parent_id → та же таблица)
                implicit.append({
                    "column": col_name,
                    "foreign_table": table_name,
                    "foreign_column": "id",
                    "source": "implicit"
                })
                continue

        # 2. Прямые кандидаты по имени
        candidates = [
            base + "s",       # project → projects
            base + "es",      # status → statuses
            base,             # sprint → sprint
        ]
        if base.endswith("y"):
            candidates.append(base[:-1] + "ies")  # priority → priorities, category → categories
        if base.endswith("s"):
            candidates.append(base)

        matched_table = None
        for candidate in candidates:
            if candidate in all_tables and candidate != table_name:
                matched_table = candidate
                break

        # 3. Если прямое не нашло — пробуем с доменными префиксами
        if not matched_table:
            # Получаем «домен» из имени текущей таблицы (issue_comments → issue)
            # и пробуем prefix_base (issue_status, issue_priority, etc.)
            prefixes_to_try = set()
            # Из имени таблицы: issues → issue, issue_comments → issue
            parts = table_name.split("_")
            if parts:
                singular = parts[0].rstrip("s")
                prefixes_to_try.add(singular)       # "issue"
                prefixes_to_try.add(parts[0])       # "issues"

            # Также общие доменные префиксы
            prefixes_to_try.update(["issue", "project", "workflow", "notification", "permission"])

            for prefix in prefixes_to_try:
                prefix_candidates = [
                    f"{prefix}_{base}s",       # issue_statuses
                    f"{prefix}_{base}es",      # issue_statuses
                    f"{prefix}_{base}",        # issue_type
                ]
                if base.endswith("y"):
                    prefix_candidates.append(f"{prefix}_{base[:-1]}ies")  # issue_priorities
                
                for candidate in prefix_candidates:
                    if candidate in all_tables and candidate != table_name:
                        matched_table = candidate
                        break
                if matched_table:
                    break

        # 4. Последняя попытка — поиск таблиц содержащих base в имени
        if not matched_table:
            for t in all_tables:
                if t != table_name and base in t and t.endswith("s"):
                    matched_table = t
                    break

        if matched_table:
            implicit.append({
                "column": col_name,
                "foreign_table": matched_table,
                "foreign_column": "id",
                "source": "implicit"
            })

    return implicit


def build_all_relationships(table_name, columns, all_tables, explicit_fks):
    """
    Объединить явные FK и неявные связи.
    При множественных ссылках на одну таблицу — генерировать алиасы.
    Возвращает список join-записей:
      [{"column": "assignee_id", "foreign_table": "users", "alias": "users_assignee",
        "foreign_column": "id", "relationship": "many_to_one"}]
    """
    # Собираем все связи
    all_rels = []
    for fk in explicit_fks:
        all_rels.append({**fk, "source": "explicit"})

    implicit = detect_implicit_relationships(table_name, columns, all_tables, explicit_fks)
    all_rels.extend(implicit)

    if not all_rels:
        return []

    # Считаем сколько раз каждая таблица фигурирует как цель
    target_count = {}
    for rel in all_rels:
        t = rel["foreign_table"]
        target_count[t] = target_count.get(t, 0) + 1

    # Генерируем записи с алиасами
    joins = []
    for rel in all_rels:
        target = rel["foreign_table"]
        col = rel["column"]
        base = col[:-3] if col.endswith("_id") else col  # assignee_id → assignee

        # Если таблица используется >1 раз — алиас обязателен
        if target_count[target] > 1:
            alias = f"{target}_{base}"  # users_assignee, users_reporter
        else:
            alias = target

        joins.append({
            "column": col,
            "foreign_table": target,
            "alias": alias,
            "foreign_column": rel.get("foreign_column", "id"),
            "relationship": "many_to_one",
            "source": rel.get("source", "explicit")
        })

    return joins


def _parse_json_safe(text):
    """Робастный парсинг JSON из ответа LLM"""
    import json as _json
    import re

    text = text.strip()
    # Убираем markdown
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    # Типографские кавычки
    for old, new in [('\u201c', '"'), ('\u201d', '"'), ('\u00ab', '"'), ('\u00bb', '"'),
                     ('\u2018', "'"), ('\u2019', "'")]:
        text = text.replace(old, new)
    # Ищем JSON-блок
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        cleaned = match.group()
        cleaned = re.sub(r',\s*}', '}', cleaned)
        cleaned = re.sub(r',\s*]', ']', cleaned)
        return _json.loads(cleaned)
    return _json.loads(text)


def suggest_joins_via_llm(llm, table_name, columns, detected_joins, all_tables):
    """
    Попросить GigaChat дать осмысленные описания для джойнов
    и предложить дополнительные связи, которые не были обнаружены автоматически.
    """
    if not detected_joins and not columns:
        return {}

    # Формируем текст уже найденных связей
    join_lines = []
    for j in detected_joins:
        join_lines.append(f"{j['column']} → {j['foreign_table']} (алиас: {j['alias']})")
    detected_text = "Связи:\n" + "\n".join(f"  - {l}" for l in join_lines)

    # Колонки с _id которые не попали в detected
    detected_cols = {j["column"] for j in detected_joins}
    unmatched_id_cols = [
        c["name"] for c in columns
        if c["name"].endswith("_id") and c["name"] != "id" and c["name"] not in detected_cols
    ]

    unmatched_text = ""
    if unmatched_id_cols:
        unmatched_text = f"\nНеразрешённые колонки: {', '.join(unmatched_id_cols)}"

    prompt = f"""Для каждой связи таблицы {table_name} дай title (1-2 слова) и description (1 предложение) на русском.

{detected_text}{unmatched_text}

Ответ строго в формате JSON:
{{"joins": [{{"column": "col_id", "title": "Название", "description": "Описание"}}], "extra_joins": []}}"""

    try:
        response = llm.invoke(prompt)
        return _parse_json_safe(response.content)
    except Exception as e:
        print(f"  ⚠️ GigaChat не смог описать связи {table_name}: {e}")
        return {}


# ============================================================
# Генерация описаний через GigaChat
# ============================================================

def generate_descriptions(llm, table_name, columns, fks, sample_columns, sample_rows, row_count):
    """
    Попросить GigaChat сгенерировать описания для таблицы и колонок.
    При неудаче с большой таблицей — разбивает на 2 запроса.
    """
    # Форматируем примеры данных (не более 3 строк, укороченные значения)
    sample_text = ""
    if sample_rows:
        sample_text = "\nПримеры:\n"
        for row in sample_rows[:2]:
            parts = []
            for col, val in zip(sample_columns, row):
                val_str = str(val)[:50] if val is not None else "NULL"
                parts.append(f"{col}={val_str}")
            sample_text += "  " + ", ".join(parts[:8]) + "\n"

    columns_text = "\n".join(
        f"  - {c['name']} ({c['data_type']})"
        for c in columns
    )

    prompt = f"""Опиши таблицу {table_name} ({row_count} строк) на русском. Колонки:
{columns_text}
{sample_text}
Ответ строго JSON:
{{"table_title": "Русское название (2-3 слова)", "table_description": "Описание (1-2 предложения)", "columns": {{"col_name": {{"title": "Название", "description": "Что хранит"}}}}}}"""

    # Попытка 1
    try:
        response = llm.invoke(prompt)
        return _parse_json_safe(response.content)
    except Exception:
        pass

    # Попытка 2: упрощённый промпт (для больших таблиц)
    short_cols = ", ".join(c["name"] for c in columns)
    prompt2 = f"""Таблица {table_name}. Колонки: {short_cols}.
Дай table_title (2 слова на русском) и table_description (1 предложение).
Для каждой колонки дай title (1-2 слова) и description (кратко).
Ответ: JSON {{"table_title":"...", "table_description":"...", "columns":{{"col":{{"title":"...", "description":"..."}}}}}}"""

    try:
        response = llm.invoke(prompt2)
        return _parse_json_safe(response.content)
    except Exception as e:
        print(f"  ⚠️ GigaChat не смог описать {table_name}: {e}")

    # Fallback — базовые описания
    result = {
        "table_title": table_name.replace("_", " ").title(),
        "table_description": f"Таблица {table_name}",
        "columns": {}
    }
    for c in columns:
        result["columns"][c["name"]] = {
            "title": c["name"].replace("_", " ").replace("id", "").strip().title() or c["name"],
            "description": f"{c['name']} ({c['data_type']})"
        }
    return result


# ============================================================
# Маппинг типов PostgreSQL → Cube.js
# ============================================================

def pg_type_to_cube(pg_type, column_name):
    """Сопоставить тип PostgreSQL с типом Cube.js"""
    pg_type = pg_type.lower()
    
    # Время
    if any(t in pg_type for t in ["timestamp", "date", "time"]):
        return "time"
    
    # Числа
    if any(t in pg_type for t in ["integer", "int", "bigint", "smallint", "serial",
                                    "numeric", "decimal", "real", "double", "float"]):
        return "number"
    
    # Булевы
    if "boolean" in pg_type:
        return "boolean"
    
    # Строки (по умолчанию)
    return "string"


# ============================================================
# Генерация Cube YAML
# ============================================================

def generate_cube_yaml(table_name, columns, enriched_joins, pk, descriptions,
                       schema="public", jira_plan=None):
    """
    Сгенерировать YAML-модель Cube для одной таблицы.
    enriched_joins — результат build_all_relationships + описания от LLM.
    jira_plan — данные из JIRA execution plan (для доп. мер).
    """
    
    desc = descriptions
    cube_name = table_name
    
    cube = {
        "name": cube_name,
        "sql_table": f"{schema}.{table_name}",
        "title": desc.get("table_title", table_name),
        "description": desc.get("table_description", ""),
    }
    
    # --- Joins (обогащённые: FK + implicit + LLM) ---
    joins = []
    join_columns = set()  # колонки, задействованные в join
    
    for j in enriched_joins:
        alias = j["alias"]
        col = j["column"]
        foreign_col = j.get("foreign_column", "id")
        join_columns.add(col)
        
        join_entry = {
            "name": alias,
            "sql": "{CUBE}." + col + " = {" + alias + "}." + foreign_col,
            "relationship": j.get("relationship", "many_to_one"),
        }
        # Добавляем описание если есть
        if j.get("title"):
            join_entry["title"] = j["title"]
        if j.get("description"):
            join_entry["description"] = j["description"]
        
        joins.append(join_entry)
    
    if joins:
        cube["joins"] = joins
    
    # --- Dimensions ---
    dimensions = []
    col_descs = desc.get("columns", {})
    
    for c in columns:
        col_name = c["name"]
        cube_type = pg_type_to_cube(c["data_type"], col_name)
        
        # Пропускаем FK-колонки (они уходят через join)
        if col_name in join_columns and col_name != pk:
            continue
        
        dim = {
            "name": col_name,
            "sql": col_name,
            "type": cube_type,
        }
        
        if col_name == pk:
            dim["primary_key"] = True
        
        col_desc = col_descs.get(col_name, {})
        if col_desc.get("title"):
            dim["title"] = col_desc["title"]
        if col_desc.get("description"):
            dim["description"] = col_desc["description"]
        
        dimensions.append(dim)
    
    cube["dimensions"] = dimensions
    
    # --- Measures ---
    measures = [
        {
            "name": "count",
            "type": "count",
            "title": "Количество",
            "description": f"Общее количество записей в таблице {desc.get('table_title', table_name)}"
        }
    ]
    
    # Добавляем sum/avg для числовых колонок (не ID и не FK)
    for c in columns:
        col_name = c["name"]
        if col_name.endswith("_id") or col_name == pk:
            continue
        if pg_type_to_cube(c["data_type"], col_name) == "number":
            col_title = col_descs.get(col_name, {}).get("title", col_name)
            measures.append({
                "name": f"total_{col_name}",
                "sql": col_name,
                "type": "sum",
                "title": f"Сумма {col_title}",
                "description": f"Сумма значений поля {col_name}"
            })
            measures.append({
                "name": f"avg_{col_name}",
                "sql": col_name,
                "type": "avg",
                "title": f"Среднее {col_title}",
                "description": f"Среднее значение поля {col_name}"
            })
    
    # JIRA-специфичные меры из Knowledge Base
    jira_measures = get_jira_suggested_measures(table_name)
    existing_names = {m["name"] for m in measures}
    for jm in jira_measures:
        if jm["name"] not in existing_names:
            measures.append(jm)

    cube["measures"] = measures
    
    return {"cubes": [cube]}


# ============================================================
# Генерация semantic-конфигов (glossary, examples)
# ============================================================

def generate_glossary(all_tables_info):
    """Сгенерировать базовый glossary.yml"""
    glossary = {}
    
    for info in all_tables_info:
        table = info["table_name"]
        desc = info["descriptions"]
        cube_name = table
        
        # Термин для таблицы
        title = desc.get("table_title", table)
        glossary[table] = {
            "aliases": [title.lower(), table, table.replace("_", " ")],
            "semantic_type": "entity",
            "fields": [f"{cube_name}.id"],
            "filter_operator": "equals",
            "description": desc.get("table_description", "")
        }
        
        # Термин count для таблицы
        glossary[f"{table}_count"] = {
            "aliases": [
                f"количество {title.lower()}",
                f"сколько {title.lower()}",
            ],
            "semantic_type": "metric",
            "measures": [f"{cube_name}.count"],
            "description": f"Количество записей {title}"
        }
    
    return glossary


def generate_examples(all_tables_info):
    """Сгенерировать базовый examples.yml"""
    examples = []
    
    for info in all_tables_info:
        table = info["table_name"]
        desc = info["descriptions"]
        cube_name = table
        title = desc.get("table_title", table)
        
        # Пример: "сколько <сущностей>"
        examples.append({
            "question": f"сколько {title.lower()}",
            "intent": "analytics",
            "query": {
                "measures": [f"{cube_name}.count"],
                "limit": 100
            },
            "tags": ["count", table]
        })
        
        # Пример: "список <сущностей>"
        dims = []
        for c in info["columns"][:5]:
            if c["name"] != "id" and not c["name"].endswith("_id"):
                dims.append(f"{cube_name}.{c['name']}")
        
        if dims:
            examples.append({
                "question": f"список {title.lower()}",
                "intent": "analytics",
                "query": {
                    "measures": [f"{cube_name}.count"],
                    "dimensions": dims[:4],
                    "limit": 100
                },
                "tags": ["list", table]
            })
    
    return examples


# ============================================================
# MAIN
# ============================================================

def main():
    # Разбор аргументов
    parser = argparse.ArgumentParser(description="Загрузчик данных в Cube")
    parser.add_argument("--source", choices=["postgresql", "greenplum", "hive", "duckdb", "cube"],
                        help="Переопределить database.driver из config.yml")
    parser.add_argument("--jira-plan", metavar="FILE",
                        help="Путь к файлу JIRA execution plan (xlsx/csv) для обогащения моделей")
    args = parser.parse_args()

    print("=" * 60)
    print("  ЗАГРУЗЧИК ДАННЫХ В CUBE")
    print("  Источник → Описания GigaChat → YAML-модели Cube")
    print("=" * 60)
    print()
    
    # 1. Загрузить конфиг
    config = load_config()
    print("✅ Конфигурация загружена")
    
    # 2. Подключиться к источнику данных
    source, driver_name = create_data_source(config, args.source)
    schema = config.get("database", {}).get("schema", "public")
    print(f"   Источник: {driver_name}, Схема: {schema}")
    
    # 3. Загрузить JIRA plan (если указан)
    jira_plan = {}
    plan_file = args.jira_plan or config.get("jira_plan_path")
    if plan_file and Path(plan_file).exists():
        jira_plan = load_jira_plan(plan_file)
    elif plan_file:
        print(f"⚠️  JIRA plan файл не найден: {plan_file}")

    # 4. Подключить GigaChat
    print("🔄 Подключение к GigaChat...")
    llm = create_gigachat(config)
    print("✅ GigaChat готов")
    
    # 4. Получить список таблиц
    tables = source.get_tables()
    print(f"\n📋 Найдено таблиц: {len(tables)}")
    for t in tables:
        print(f"   - {t}")
    print()
    
    # 5. Обработать каждую таблицу
    model_path = Path(config["cube"]["model_path"])
    model_path.mkdir(parents=True, exist_ok=True)
    
    all_tables_set = set(tables)
    all_tables_info = []
    
    for i, table in enumerate(tables, 1):
        print(f"[{i}/{len(tables)}] Обработка таблицы: {table}")
        
        # Читаем структуру через унифицированный интерфейс
        columns = source.get_columns(table)
        fks = source.get_foreign_keys(table)
        pk = source.get_primary_key(table)
        row_count = source.get_row_count(table)
        sample_cols, sample_rows = source.get_sample_data(table, 5)
        
        print(f"   Колонок: {len(columns)}, FK: {len(fks)}, Строк: {row_count}")
        
        # Обнаруживаем все связи (FK + implicit по именам)
        enriched_joins = build_all_relationships(table, columns, all_tables_set, fks)
        implicit_count = sum(1 for j in enriched_joins if j.get("source") == "implicit")
        if enriched_joins:
            print(f"   🔗 Связей: {len(enriched_joins)} (FK: {len(fks)}, по именам: {implicit_count})")
            for j in enriched_joins:
                src = "FK" if j["source"] == "explicit" else "→"
                print(f"      {src} {j['column']} → {j['foreign_table']} (as {j['alias']})")
        
        # Просим GigaChat описать связи (если они есть)
        if enriched_joins:
            print(f"   🤖 GigaChat: описание связей...")
            join_suggestions = suggest_joins_via_llm(llm, table, columns, enriched_joins, all_tables_set)
            
            # Обогащаем joins описаниями от LLM
            llm_joins_map = {}
            for lj in join_suggestions.get("joins", []):
                key = lj.get("column", "")
                llm_joins_map[key] = lj
            
            for j in enriched_joins:
                llm_info = llm_joins_map.get(j["column"], {})
                if llm_info.get("title"):
                    j["title"] = llm_info["title"]
                if llm_info.get("description"):
                    j["description"] = llm_info["description"]
                if llm_info.get("alias") and llm_info["alias"] != j["alias"]:
                    j["alias"] = llm_info["alias"]
            
            # Добавляем extra_joins от LLM
            for extra in join_suggestions.get("extra_joins", []):
                extra_table = extra.get("foreign_table", "")
                if extra_table in all_tables_set and extra_table != table:
                    col_names = {c["name"] for c in columns}
                    if extra.get("column") in col_names:
                        enriched_joins.append({
                            "column": extra["column"],
                            "foreign_table": extra_table,
                            "alias": extra.get("alias", extra_table),
                            "foreign_column": extra.get("foreign_column", "id"),
                            "relationship": "many_to_one",
                            "title": extra.get("title", ""),
                            "description": extra.get("description", ""),
                            "source": "llm"
                        })
                        print(f"      ✨ LLM предложил: {extra['column']} → {extra_table}")
        
        # Генерируем описания через GigaChat
        print(f"   🤖 GigaChat: описания таблицы и колонок...")
        descriptions = generate_descriptions(
            llm, table, columns, fks, sample_cols, sample_rows, row_count
        )

        # Обогащаем описания из JIRA Knowledge Base
        jira_hints = match_jira_hints(table, jira_plan)
        if jira_hints:
            print(f"   📚 JIRA KB: {jira_hints.get('title', 'match found')}")
            descriptions = enrich_descriptions_with_jira(descriptions, table, columns, jira_plan)
            if not descriptions.get("table_description") or len(descriptions["table_description"]) < 10:
                descriptions["table_description"] = jira_hints.get("description", descriptions.get("table_description", ""))
            if not descriptions.get("table_title") or descriptions["table_title"] == table:
                descriptions["table_title"] = jira_hints.get("title", descriptions.get("table_title", table))

        print(f"   ✅ Описания: {descriptions.get('table_title', '?')}")
        
        # Генерируем Cube YAML
        cube_schema = schema if driver_name != "duckdb" else "main"
        cube_yaml = generate_cube_yaml(table, columns, enriched_joins, pk, descriptions,
                                        cube_schema, jira_plan)
        
        # Сохраняем
        yaml_path = model_path / f"{table}.yml"
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(cube_yaml, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
        print(f"   💾 Сохранено: {yaml_path}")
        
        all_tables_info.append({
            "table_name": table,
            "columns": columns,
            "fks": fks,
            "enriched_joins": enriched_joins,
            "descriptions": descriptions
        })
        print()
    
    # 6. Генерируем semantic-конфиги
    config_path = Path("config")
    config_path.mkdir(exist_ok=True)
    
    print("📝 Генерация glossary.yml...")
    glossary = generate_glossary(all_tables_info)
    with open(config_path / "glossary.yml", 'w', encoding='utf-8') as f:
        yaml.dump(glossary, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    print("📝 Генерация examples.yml...")
    examples = generate_examples(all_tables_info)
    with open(config_path / "examples.yml", 'w', encoding='utf-8') as f:
        yaml.dump(examples, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    print("📝 Генерация semantic_layer.yml...")
    layer_config = {
        "cube": {
            "base_url": config["cube"]["api_url"],
            "enabled": True,
            "preferred_cubes": [t["table_name"] for t in all_tables_info]
        },
        "intents": {
            "analytics": {
                "description": "Аналитические запросы через Cube",
                "keywords": ["сколько", "количество", "покажи", "список",
                             "средний", "сумма", "топ", "всего", "по проектам"],
                "priority": 1
            }
        },
        "query_generation": {
            "default_limit": 100,
            "max_limit": 10000
        }
    }
    with open(config_path / "semantic_layer.yml", 'w', encoding='utf-8') as f:
        yaml.dump(layer_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    source.close()
    
    # Сводка по связям
    total_joins = sum(len(info.get("enriched_joins", [])) for info in all_tables_info)
    fk_joins = sum(
        sum(1 for j in info.get("enriched_joins", []) if j.get("source") == "explicit")
        for info in all_tables_info
    )
    implicit_joins = sum(
        sum(1 for j in info.get("enriched_joins", []) if j.get("source") == "implicit")
        for info in all_tables_info
    )
    llm_joins = sum(
        sum(1 for j in info.get("enriched_joins", []) if j.get("source") == "llm")
        for info in all_tables_info
    )
    
    print()
    print("=" * 60)
    print("  ✅ ГОТОВО!")
    print("=" * 60)
    print(f"""
Источник данных: {driver_name}
Созданные файлы:
  📁 {model_path}/          — YAML-модели Cube ({len(tables)} файлов)
  📁 config/glossary.yml    — Бизнес-глоссарий
  📁 config/examples.yml    — Примеры запросов
  📁 config/semantic_layer.yml — Конфигурация семантического слоя

Обнаруженные связи (joins):
  🔗 Всего: {total_joins}
     - Из FK constraints: {fk_joins}
     - По именам колонок: {implicit_joins}
     - Предложено GigaChat: {llm_joins}

Следующие шаги:
  1. Скопируйте файлы из {model_path}/ в папку model/cubes/ вашего Cube-проекта
  2. ПРОВЕРЬТЕ СВЯЗИ: откройте YAML-файлы и убедитесь что joins корректны
  3. Перезапустите Cube: npx cubejs-server
  4. Проверьте: curl http://localhost:4000/cubejs-api/v1/meta
  5. Отредактируйте glossary.yml и examples.yml под ваши задачи
  6. Запустите 02_build_faiss.py для создания векторного индекса
  7. Откройте 03_agent.ipynb в JupyterLab и задавайте вопросы
""")


if __name__ == "__main__":
    main()
