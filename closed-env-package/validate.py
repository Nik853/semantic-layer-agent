"""
=================================================================
ВАЛИДАЦИЯ ПАКЕТА ПЕРЕД ДЕПЛОЕМ
=================================================================
Проверяет ВСЮ цепочку: config → DB → GigaChat → Cube → FAISS → agent
Запускайте ПЕРЕД выгрузкой во внешний контур.

Запуск:  python validate.py
         python validate.py --fix    (попытается исправить мелкие проблемы)
=================================================================
"""

import os
import sys
import json
import traceback
from pathlib import Path

# ============================================================
# Результаты проверок
# ============================================================

class Validator:
    def __init__(self):
        self.checks = []
        self.config = None
        self.fix_mode = "--fix" in sys.argv
    
    def ok(self, name, detail=""):
        self.checks.append(("OK", name, detail))
        print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))
    
    def warn(self, name, detail=""):
        self.checks.append(("WARN", name, detail))
        print(f"  ⚠️  {name}" + (f" — {detail}" if detail else ""))
    
    def fail(self, name, detail=""):
        self.checks.append(("FAIL", name, detail))
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))
    
    def skip(self, name, detail=""):
        self.checks.append(("SKIP", name, detail))
        print(f"  ⏭️  {name}" + (f" — {detail}" if detail else ""))
    
    def summary(self):
        ok_count = sum(1 for s, _, _ in self.checks if s == "OK")
        warn_count = sum(1 for s, _, _ in self.checks if s == "WARN")
        fail_count = sum(1 for s, _, _ in self.checks if s == "FAIL")
        skip_count = sum(1 for s, _, _ in self.checks if s == "SKIP")
        total = len(self.checks)
        
        print()
        print("=" * 60)
        if fail_count == 0:
            print("  ✅ ВАЛИДАЦИЯ ПРОЙДЕНА")
            print(f"     {ok_count}/{total} OK, {warn_count} предупреждений, {skip_count} пропущено")
            if warn_count > 0:
                print("     Предупреждения не блокируют деплой, но рекомендуется исправить.")
        else:
            print("  ❌ ВАЛИДАЦИЯ НЕ ПРОЙДЕНА")
            print(f"     {fail_count} ошибок, {ok_count} OK, {warn_count} предупреждений")
            print()
            print("  Ошибки:")
            for status, name, detail in self.checks:
                if status == "FAIL":
                    print(f"    ❌ {name}: {detail}")
        print("=" * 60)
        return fail_count == 0


V = Validator()

# ============================================================
# 1. КОНФИГУРАЦИЯ
# ============================================================

def check_config():
    print("\n📋 1. ПРОВЕРКА КОНФИГУРАЦИИ")
    print("-" * 40)
    
    config_path = Path("config.yml")
    if not config_path.exists():
        V.fail("config.yml существует", "Файл не найден! Создайте config.yml")
        return False
    V.ok("config.yml существует")
    
    try:
        import yaml
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        V.ok("config.yml парсится")
    except Exception as e:
        V.fail("config.yml парсится", str(e))
        return False
    
    V.config = config
    
    # Проверка обязательных секций
    required_sections = ["database", "cube", "gigachat", "faiss", "agent"]
    for section in required_sections:
        if section in config and config[section]:
            V.ok(f"Секция '{section}' заполнена")
        else:
            V.fail(f"Секция '{section}' заполнена", "Секция отсутствует или пуста")
    
    # Проверка database
    db = config.get("database", {})
    driver = db.get("driver", "postgresql").lower()
    V.ok(f"database.driver: {driver}")
    
    if driver == "duckdb":
        db_path = db.get("path", "")
        if db_path:
            if Path(db_path).exists():
                size_mb = Path(db_path).stat().st_size / 1024 / 1024
                V.ok(f"database.path: {db_path} ({size_mb:.1f} MB)")
            else:
                V.warn(f"database.path: {db_path} (файл не найден)",
                       "Запустите 00_load_duckdb.py для создания")
        else:
            V.fail("database.path не указан для DuckDB")
    elif driver == "cube":
        V.ok("database.driver=cube — БД не нужна, метаданные из Cube API")
    elif driver in ("postgresql", "greenplum", "postgres"):
        if db.get("host") and db.get("host") != "localhost":
            V.ok(f"database.host: {db['host']}")
        elif db.get("host") == "localhost":
            V.warn("database.host = localhost", "Убедитесь что БД доступна в целевом окружении")
        else:
            V.fail("database.host не указан")
        
        if db.get("name") and db["name"] != "your_database":
            V.ok(f"database.name: {db['name']}")
        else:
            V.fail("database.name", "Укажите реальное имя БД")
    else:
        V.fail(f"Неизвестный database.driver: {driver}",
               "Допустимые: postgresql, greenplum, duckdb, cube")
    
    if db.get("schema"):
        V.ok(f"database.schema: {db['schema']}")
    else:
        V.warn("database.schema не указан", "Будет использована схема 'public'")
    
    # Проверка GigaChat — хотя бы один режим
    gc = config.get("gigachat", {})
    if gc.get("base_url"):
        V.ok(f"GigaChat режим: прокси ({gc['base_url']})")
        token_env = gc.get("access_token_env", "JPY_API_TOKEN")
        if os.getenv(token_env):
            V.ok(f"Env ${token_env} установлена")
        else:
            V.warn(f"Env ${token_env} не найдена локально", 
                   "Убедитесь что она есть в целевом окружении")
    elif gc.get("credentials"):
        V.ok("GigaChat режим: credentials")
    else:
        V.fail("GigaChat не настроен", 
               "Заполните gigachat.credentials или gigachat.base_url")
    
    # Проверка Cube URL
    cube_url = config.get("cube", {}).get("api_url", "")
    if cube_url:
        V.ok(f"cube.api_url: {cube_url}")
    else:
        V.fail("cube.api_url не указан")
    
    # Проверка FAISS
    faiss_cfg = config.get("faiss", {})
    if faiss_cfg.get("embedding_model"):
        V.ok(f"faiss.embedding_model: {faiss_cfg['embedding_model']}")
    else:
        V.fail("faiss.embedding_model не указан")
    
    return True


# ============================================================
# 2. ФАЙЛЫ ПАКЕТА
# ============================================================

def check_files():
    print("\n📋 2. ПРОВЕРКА ФАЙЛОВ ПАКЕТА")
    print("-" * 40)
    
    required_files = [
        ("00_load_duckdb.py", "Загрузка Parquet/CSV в DuckDB"),
        ("01_data_loader.py", "Скрипт загрузки данных"),
        ("02_build_faiss.py", "Скрипт построения FAISS"),
        ("03_agent.ipynb",    "Jupyter-ноутбук агента"),
        ("config.yml",        "Конфигурация"),
        ("cube.env.example",  "Шаблон .env для Cube"),
    ]
    
    for fname, desc in required_files:
        p = Path(fname)
        if p.exists():
            size = p.stat().st_size
            V.ok(f"{fname} ({size:,} байт)", desc)
        else:
            V.fail(f"{fname} отсутствует", desc)
    
    # Проверка что скрипты используют config, а не хардкод
    for script in ["01_data_loader.py", "02_build_faiss.py"]:
        if not Path(script).exists():
            continue
        content = Path(script).read_text(encoding='utf-8')
        
        # Проверяем что нет хардкода схемы
        hardcoded_schemas = []
        for marker in ["'public'.", '"public".', "'dbo'.", '"dbo".']:
            if marker in content.lower() and "schema" not in content[:content.find(marker) + 200]:
                hardcoded_schemas.append(marker)
        
        if hardcoded_schemas:
            V.warn(f"{script}: возможный хардкод схемы", 
                   f"Найдено: {hardcoded_schemas}")
        
        # Проверяем что конфиг загружается
        if "load_config" in content or "config.yml" in content:
            V.ok(f"{script}: использует config.yml")
        else:
            V.fail(f"{script}: не загружает config.yml")
    
    # Проверка ноутбука
    if Path("03_agent.ipynb").exists():
        try:
            with open("03_agent.ipynb", 'r', encoding='utf-8') as f:
                nb = json.load(f)
            cell_count = len(nb.get("cells", []))
            V.ok(f"03_agent.ipynb: {cell_count} ячеек, валидный JSON")
            
            # Проверяем что нет хардкода GigaChat
            all_code = ""
            for cell in nb["cells"]:
                if cell.get("cell_type") == "code":
                    all_code += "".join(cell.get("source", []))
            
            if 'gc.get("base_url")' in all_code or "gc.get('base_url')" in all_code:
                V.ok("03_agent.ipynb: GigaChat режим из конфига")
            elif "base_url=" in all_code and "config" not in all_code.split("base_url=")[0][-200:]:
                V.warn("03_agent.ipynb: возможный хардкод base_url GigaChat")
            
            if "glossary_path" in all_code and ("sem.get" in all_code or "CONFIG" in all_code):
                V.ok("03_agent.ipynb: пути glossary/examples из конфига")
            elif "/home/" in all_code or "/opt/" in all_code:
                V.warn("03_agent.ipynb: обнаружены абсолютные пути", 
                       "Перенесите пути в config.yml секцию semantic")
            
        except Exception as e:
            V.fail(f"03_agent.ipynb: невалидный JSON", str(e))


# ============================================================
# 3. ПОДКЛЮЧЕНИЕ К БД
# ============================================================

def check_database():
    print("\n📋 3. ПРОВЕРКА ПОДКЛЮЧЕНИЯ К ДАННЫМ")
    print("-" * 40)
    
    config = V.config
    if not config:
        V.skip("Подключение к данным", "config.yml не загружен")
        return
    
    db = config.get("database", {})
    driver = db.get("driver", "postgresql").lower()
    
    if driver == "cube":
        V.ok("driver=cube — БД-подключение не требуется")
        V.ok("Метаданные будут прочитаны из Cube API")
        return
    
    if driver == "duckdb":
        db_path = db.get("path", "./data.duckdb")
        if not Path(db_path).exists():
            V.warn(f"DuckDB файл не найден: {db_path}",
                   "Запустите: python 00_load_duckdb.py --data-dir ./data")
            return
        try:
            import duckdb
            conn = duckdb.connect(db_path, read_only=True)
            schema = db.get("schema", "main")
            tables = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = ? AND table_type = 'BASE TABLE'",
                [schema]
            ).fetchone()[0]
            V.ok(f"DuckDB: {db_path}")
            if tables > 0:
                V.ok(f"Схема '{schema}': {tables} таблиц")
            else:
                V.warn(f"Схема '{schema}': 0 таблиц",
                       "Загрузите данные: python 00_load_duckdb.py")
            conn.close()
        except ImportError:
            V.warn("duckdb не установлен", "pip install duckdb")
        except Exception as e:
            V.fail(f"DuckDB: {e}")
        return
    
    # PostgreSQL / GreenPlum
    if db.get("name") == "your_database" or not db.get("name"):
        V.skip("Подключение к БД", "Используются значения по умолчанию")
        return
    
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=db.get("host", "localhost"),
            port=db.get("port", 5432),
            dbname=db["name"],
            user=db.get("user", ""),
            password=db.get("password", ""),
            connect_timeout=5
        )
        V.ok(f"Подключение к {db['name']}@{db.get('host', 'localhost')}")
        
        schema = db.get("schema", "public")
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
        """, (schema,))
        table_count = cur.fetchone()[0]
        
        if table_count > 0:
            V.ok(f"Схема '{schema}': {table_count} таблиц")
        else:
            V.fail(f"Схема '{schema}': 0 таблиц", "Проверьте database.schema в config.yml")
        
        cur.close()
        conn.close()
        
    except ImportError:
        V.warn("psycopg2 не установлен", "pip install psycopg2-binary")
    except Exception as e:
        err = str(e).strip().split("\n")[0]
        V.fail(f"Подключение к БД", err)


# ============================================================
# 4. ПОДКЛЮЧЕНИЕ К GigaChat
# ============================================================

def check_gigachat():
    print("\n📋 4. ПРОВЕРКА GigaChat")
    print("-" * 40)
    
    config = V.config
    if not config:
        V.skip("GigaChat", "config.yml не загружен")
        return
    
    gc = config.get("gigachat", {})
    
    if not gc.get("base_url") and not gc.get("credentials"):
        V.skip("GigaChat", "Не настроен (ни base_url, ни credentials)")
        return
    
    try:
        from langchain_gigachat import GigaChat
        
        if gc.get("base_url"):
            token_env = gc.get("access_token_env", "JPY_API_TOKEN")
            token = os.getenv(token_env, "")
            if not token:
                V.warn(f"GigaChat: ${token_env} не установлена",
                       "Тест-запрос может не сработать локально")
                # Try anyway in case the proxy doesn't need auth
            llm = GigaChat(
                base_url=gc["base_url"],
                access_token=token,
                model=gc.get("model", "GigaChat")
            )
        else:
            llm = GigaChat(
                credentials=gc["credentials"],
                model=gc.get("model", "GigaChat"),
                verify_ssl_certs=gc.get("verify_ssl", False),
                timeout=gc.get("timeout", 60)
            )
        
        resp = llm.invoke("Скажи одно слово: 'работает'")
        if resp and resp.content:
            V.ok(f"GigaChat отвечает", f"'{resp.content.strip()[:50]}'")
        else:
            V.fail("GigaChat: пустой ответ")
        
    except ImportError:
        V.warn("langchain-gigachat не установлен", "pip install langchain-gigachat")
    except Exception as e:
        err = str(e).strip().split("\n")[0][:100]
        V.warn(f"GigaChat: {err}",
               "Возможно, недоступен локально — проверьте в целевом окружении")


# ============================================================
# 5. ПРОВЕРКА Cube API
# ============================================================

def check_cube():
    print("\n📋 5. ПРОВЕРКА Cube API")
    print("-" * 40)
    
    config = V.config
    if not config:
        V.skip("Cube API", "config.yml не загружен")
        return
    
    cube_url = config.get("cube", {}).get("api_url", "")
    if not cube_url:
        V.fail("cube.api_url не задан")
        return
    
    try:
        import httpx
        headers = {}
        token = config.get("cube", {}).get("api_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        client = httpx.Client(timeout=10.0)
        resp = client.get(f"{cube_url}/meta", headers=headers)
        
        if resp.status_code == 200:
            meta = resp.json()
            cubes = meta.get("cubes", [])
            total_measures = sum(len(c.get("measures", [])) for c in cubes)
            total_dims = sum(len(c.get("dimensions", [])) for c in cubes)
            V.ok(f"Cube API доступен", 
                 f"{len(cubes)} кубов, {total_measures} мер, {total_dims} измерений")
            
            # Проверяем что модели загружены
            if len(cubes) == 0:
                V.warn("Cube: 0 кубов", "Запустите 01_data_loader.py и перезапустите Cube")
            
            # Тестовый запрос — count по первому кубу
            if cubes:
                first_cube = cubes[0]["name"]
                measures = cubes[0].get("measures", [])
                count_measure = None
                for m in measures:
                    if m.get("type") == "count":
                        count_measure = m["name"]
                        break
                
                if count_measure:
                    test_query = {"measures": [count_measure], "limit": 1}
                    resp2 = client.post(
                        f"{cube_url}/load",
                        json={"query": test_query},
                        headers={**headers, "Content-Type": "application/json"}
                    )
                    if resp2.status_code == 200:
                        data = resp2.json().get("data", [])
                        if data:
                            val = list(data[0].values())[0]
                            V.ok(f"Тест-запрос: {count_measure} = {val}")
                        else:
                            V.warn(f"Тест-запрос вернул 0 строк")
                    else:
                        V.warn(f"Тест-запрос: HTTP {resp2.status_code}")
        else:
            V.fail(f"Cube API: HTTP {resp.status_code}", resp.text[:200])
        
    except ImportError:
        V.warn("httpx не установлен", "pip install httpx")
    except Exception as e:
        err = str(e).strip().split("\n")[0][:100]
        V.warn(f"Cube API недоступен: {err}",
               "Возможно, Cube не запущен локально — проверьте в целевом окружении")


# ============================================================
# 6. ПРОВЕРКА FAISS-ИНДЕКСА
# ============================================================

def check_faiss():
    print("\n📋 6. ПРОВЕРКА FAISS-ИНДЕКСА")
    print("-" * 40)
    
    config = V.config
    if not config:
        V.skip("FAISS", "config.yml не загружен")
        return
    
    index_path = Path(config.get("faiss", {}).get("index_path", "./faiss_index"))
    
    if not index_path.exists():
        V.warn(f"FAISS-индекс не найден: {index_path}",
               "Запустите 02_build_faiss.py после настройки Cube")
        return
    
    # Проверяем файлы индекса
    expected_files = ["index.faiss", "index.pkl", "members.json"]
    for fname in expected_files:
        fpath = index_path / fname
        if fpath.exists():
            size = fpath.stat().st_size
            V.ok(f"{fname} ({size:,} байт)")
        else:
            V.fail(f"{fname} отсутствует в {index_path}")
    
    # Проверяем members.json
    members_path = index_path / "members.json"
    if members_path.exists():
        try:
            with open(members_path, 'r', encoding='utf-8') as f:
                members = json.load(f)
            
            measures = [m for m in members if m.get("member_type") == "measure"]
            dims = [m for m in members if m.get("member_type") == "dimension"]
            cubes = set(m.get("cube_name") for m in members)
            
            V.ok(f"members.json: {len(members)} мемберов",
                 f"{len(cubes)} кубов, {len(measures)} мер, {len(dims)} измерений")
            
            # Проверяем что есть описания
            with_desc = sum(1 for m in members if m.get("description"))
            pct = int(with_desc / max(len(members), 1) * 100)
            if pct >= 50:
                V.ok(f"Описания: {with_desc}/{len(members)} ({pct}%)")
            else:
                V.warn(f"Мало описаний: {with_desc}/{len(members)} ({pct}%)",
                       "Перегенерируйте модели через 01_data_loader.py")
            
        except Exception as e:
            V.fail("members.json: ошибка парсинга", str(e))
    
    # Пробуем загрузить FAISS
    try:
        from langchain_community.vectorstores import FAISS
        from langchain_community.embeddings import HuggingFaceEmbeddings
        
        model_name = config["faiss"]["embedding_model"]
        embeddings = HuggingFaceEmbeddings(model_name=model_name)
        store = FAISS.load_local(str(index_path), embeddings, allow_dangerous_deserialization=True)
        
        # Тестовый поиск
        results = store.similarity_search_with_score("количество", k=3)
        if results:
            best = results[0]
            V.ok(f"FAISS-поиск работает",
                 f"'{best[0].metadata.get('name', '?')}' (score={best[1]:.1f})")
        else:
            V.warn("FAISS-поиск: 0 результатов")
    
    except ImportError:
        V.warn("FAISS/sentence-transformers не установлены",
               "pip install faiss-cpu sentence-transformers")
    except Exception as e:
        err = str(e).strip().split("\n")[0][:100]
        V.fail(f"FAISS загрузка: {err}")


# ============================================================
# 7. ПРОВЕРКА CUBE-МОДЕЛЕЙ (YAML)
# ============================================================

def check_cube_models():
    print("\n📋 7. ПРОВЕРКА CUBE-МОДЕЛЕЙ (YAML)")
    print("-" * 40)
    
    config = V.config
    if not config:
        V.skip("Cube-модели", "config.yml не загружен")
        return
    
    model_path = Path(config.get("cube", {}).get("model_path", "./cube_models"))
    if not model_path.exists():
        V.warn(f"Папка моделей не найдена: {model_path}",
               "Запустите 01_data_loader.py")
        return
    
    yml_files = list(model_path.glob("*.yml"))
    if not yml_files:
        V.warn(f"Нет YAML-файлов в {model_path}")
        return
    
    V.ok(f"Найдено {len(yml_files)} YAML-моделей в {model_path}")
    
    import yaml
    schema = config.get("database", {}).get("schema", "public")
    issues = []
    
    for yf in yml_files:
        try:
            with open(yf, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            cubes = data.get("cubes", [])
            for cube in cubes:
                name = cube.get("name", "?")
                sql_table = cube.get("sql_table", "")
                
                # Проверяем что sql_table соответствует схеме
                if sql_table and not sql_table.startswith(f"{schema}."):
                    issues.append(f"{yf.name}: sql_table='{sql_table}' не соответствует schema='{schema}'")
                
                # Проверяем наличие dimensions
                dims = cube.get("dimensions", [])
                measures = cube.get("measures", [])
                if not dims and not measures:
                    issues.append(f"{yf.name}: куб '{name}' без dimensions и measures")
                
                # Проверяем наличие title/description
                if not cube.get("title"):
                    issues.append(f"{yf.name}: куб '{name}' без title")
                
        except Exception as e:
            issues.append(f"{yf.name}: ошибка парсинга — {e}")
    
    if issues:
        for issue in issues[:10]:
            V.warn(issue)
        if len(issues) > 10:
            V.warn(f"... и ещё {len(issues) - 10} проблем")
    else:
        V.ok(f"Все {len(yml_files)} моделей валидны и соответствуют schema='{schema}'")


# ============================================================
# 8. СКВОЗНОЙ ТЕСТ (end-to-end)
# ============================================================

def check_e2e():
    print("\n📋 8. СКВОЗНОЙ ТЕСТ (end-to-end)")
    print("-" * 40)
    
    config = V.config
    if not config:
        V.skip("E2E тест", "config.yml не загружен")
        return
    
    # Нужны: FAISS + GigaChat + Cube
    index_path = Path(config.get("faiss", {}).get("index_path", "./faiss_index"))
    if not (index_path / "index.faiss").exists():
        V.skip("E2E тест", "FAISS-индекс не найден")
        return
    
    gc = config.get("gigachat", {})
    if not gc.get("base_url") and not gc.get("credentials"):
        V.skip("E2E тест", "GigaChat не настроен")
        return
    
    try:
        import httpx
        cube_url = config["cube"]["api_url"]
        resp = httpx.get(f"{cube_url}/meta", timeout=5.0)
        if resp.status_code != 200:
            V.skip("E2E тест", "Cube API недоступен")
            return
    except Exception:
        V.skip("E2E тест", "Cube API недоступен")
        return
    
    try:
        from langchain_community.vectorstores import FAISS
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_gigachat import GigaChat
        
        # Загружаем компоненты
        model_name = config["faiss"]["embedding_model"]
        embeddings = HuggingFaceEmbeddings(model_name=model_name)
        store = FAISS.load_local(str(index_path), embeddings, allow_dangerous_deserialization=True)
        
        if gc.get("base_url"):
            token_env = gc.get("access_token_env", "JPY_API_TOKEN")
            llm = GigaChat(
                base_url=gc["base_url"],
                access_token=os.getenv(token_env, ""),
                model=gc.get("model", "GigaChat")
            )
        else:
            llm = GigaChat(
                credentials=gc["credentials"],
                model=gc.get("model", "GigaChat"),
                verify_ssl_certs=gc.get("verify_ssl", False),
                timeout=gc.get("timeout", 60)
            )
        
        # FAISS поиск
        test_q = "сколько записей"
        results = store.similarity_search_with_score(test_q, k=5)
        measures = [r for r in results if r[0].metadata.get("member_type") == "measure"]
        
        if not measures:
            V.warn("E2E: FAISS не нашёл подходящих мер")
            return
        
        # Формируем простой промпт
        best_measure = measures[0][0].metadata["name"]
        prompt = f"""Сгенерируй Cube.js JSON-запрос. Доступная мера: {best_measure}
Вопрос: сколько всего записей?
Ответ — ТОЛЬКО JSON: {{"measures": ["{best_measure}"], "limit": 1}}"""
        
        resp = llm.invoke(prompt)
        content = resp.content.strip()
        
        # Парсим
        import re
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:])
            if content.endswith("```"):
                content = content[:-3]
        for old, new in [('\u201c', '"'), ('\u201d', '"')]:
            content = content.replace(old, new)
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            content = match.group()
        
        query = json.loads(content)
        V.ok(f"E2E: LLM сгенерировал запрос", json.dumps(query, ensure_ascii=False)[:100])
        
        # Выполняем в Cube
        headers = {"Content-Type": "application/json"}
        token = config["cube"].get("api_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        client = httpx.Client(timeout=15.0)
        resp = client.post(
            f"{cube_url}/load",
            json={"query": query},
            headers=headers
        )
        result = resp.json()
        data = result.get("data", [])
        
        if data:
            V.ok(f"E2E: Cube вернул данные", f"{len(data)} строк, пример: {data[0]}")
        elif "error" in result:
            V.fail(f"E2E: Cube ошибка", result["error"][:100])
        else:
            V.warn("E2E: Cube вернул 0 строк")
        
    except ImportError as e:
        V.skip(f"E2E тест: не хватает пакетов", str(e))
    except json.JSONDecodeError as e:
        V.warn(f"E2E: LLM вернул невалидный JSON", f"{e}, ответ: {content[:100]}")
    except Exception as e:
        V.warn(f"E2E: {e}")


# ============================================================
# 9. СОВМЕСТИМОСТЬ С NEGGO-ОКРУЖЕНИЕМ
# ============================================================

def check_neggo_compat():
    """Проверяем что скрипты совместимы с рабочим neggo-окружением"""
    print("\n📋 9. СОВМЕСТИМОСТЬ С ЦЕЛЕВЫМ ОКРУЖЕНИЕМ")
    print("-" * 40)
    
    config = V.config
    if not config:
        V.skip("Совместимость", "config.yml не загружен")
        return
    
    # Проверяем что 01_data_loader.py поддерживает все режимы
    if Path("01_data_loader.py").exists():
        content = Path("01_data_loader.py").read_text(encoding='utf-8')
        
        if "get_schema" in content or 'schema' in content:
            V.ok("01_data_loader.py: поддерживает database.schema")
        else:
            V.fail("01_data_loader.py: не читает database.schema")
        
        if "base_url" in content and "credentials" in content:
            V.ok("01_data_loader.py: поддерживает оба режима GigaChat")
        else:
            V.warn("01_data_loader.py: проверьте поддержку обоих режимов GigaChat")
        
        if "DuckDBSource" in content or "duckdb" in content:
            V.ok("01_data_loader.py: поддерживает DuckDB")
        else:
            V.warn("01_data_loader.py: нет поддержки DuckDB")
        
        if "create_data_source" in content:
            V.ok("01_data_loader.py: универсальная фабрика источников")
        else:
            V.warn("01_data_loader.py: нет фабрики create_data_source")
    
    # Проверяем 02_build_faiss.py
    if Path("02_build_faiss.py").exists():
        content = Path("02_build_faiss.py").read_text(encoding='utf-8')
        if "config.yml" in content or "load_config" in content:
            V.ok("02_build_faiss.py: использует config.yml")
        else:
            V.fail("02_build_faiss.py: не использует config.yml")
    
    # Проверяем 03_agent.ipynb
    if Path("03_agent.ipynb").exists():
        with open("03_agent.ipynb", 'r', encoding='utf-8') as f:
            nb_content = f.read()
        
        if "base_url" in nb_content and "credentials" in nb_content:
            V.ok("03_agent.ipynb: поддерживает оба режима GigaChat")
        else:
            V.warn("03_agent.ipynb: проверьте поддержку обоих режимов GigaChat")
        
        # Проверяем на хардкод путей
        hardcoded_paths = []
        for marker in ["/home/datalab", "/opt/", "/tmp/", "/root/"]:
            if marker in nb_content:
                hardcoded_paths.append(marker)
        
        if hardcoded_paths:
            V.warn(f"03_agent.ipynb: хардкод путей: {hardcoded_paths}",
                   "Перенесите в config.yml")
        else:
            V.ok("03_agent.ipynb: нет захардкоженных абсолютных путей")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("  ВАЛИДАЦИЯ ПАКЕТА ПЕРЕД ДЕПЛОЕМ")
    print("=" * 60)
    
    check_config()
    check_files()
    check_database()
    check_gigachat()
    check_cube()
    check_faiss()
    check_cube_models()
    check_e2e()
    check_neggo_compat()
    
    success = V.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
