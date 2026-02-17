"""
=================================================================
ЗАГРУЗКА ДАННЫХ В DUCKDB
=================================================================
Скрипт создаёт DuckDB-базу из Parquet/CSV файлов.
Используйте как промежуточный шаг: GP(Spark) → Parquet → DuckDB → Cube.

Подготовка данных (в PySpark):
    df = spark.sql("SELECT * FROM schema.my_table")
    df.write.parquet("/path/to/export/my_table.parquet")
    # или
    df.toPandas().to_csv("/path/to/export/my_table.csv", index=False)

Запуск:
    python 00_load_duckdb.py                          # из ./data/
    python 00_load_duckdb.py --data-dir /path/to/export
    python 00_load_duckdb.py --data-dir ./data --db ./data.duckdb --schema main
=================================================================
"""

import os
import sys
import argparse
from pathlib import Path


def ensure_duckdb():
    """Установить duckdb если нет"""
    try:
        import duckdb
        return duckdb
    except ImportError:
        import subprocess
        print("📦 Установка duckdb...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "duckdb"])
        import duckdb
        return duckdb


def load_files_to_duckdb(data_dir, db_path, schema="main"):
    """Загрузить все Parquet/CSV файлы из директории в DuckDB"""
    duckdb = ensure_duckdb()
    
    data_dir = Path(data_dir)
    if not data_dir.exists():
        print(f"❌ Директория не найдена: {data_dir}")
        print(f"   Создайте её и положите туда Parquet/CSV файлы:")
        print(f"   mkdir -p {data_dir}")
        sys.exit(1)
    
    # Собираем файлы
    parquet_files = sorted(data_dir.glob("*.parquet"))
    csv_files = sorted(data_dir.glob("*.csv"))
    
    # Также ищем Parquet-директории (Spark создаёт директорию с part-файлами)
    parquet_dirs = []
    for d in sorted(data_dir.iterdir()):
        if d.is_dir() and list(d.glob("*.parquet")):
            parquet_dirs.append(d)
    
    total = len(parquet_files) + len(csv_files) + len(parquet_dirs)
    if total == 0:
        print(f"❌ В {data_dir} нет Parquet или CSV файлов")
        print()
        print("Как подготовить данные из GreenPlum (PySpark):")
        print("=" * 50)
        print("""
# В PySpark-ноутбуке или скрипте:

from pyspark.sql import SparkSession
spark = SparkSession.builder.enableHiveSupport().getOrCreate()

# Список таблиц для выгрузки
tables = [
    "schema.users",
    "schema.roles",
    "schema.groups",
    # ... добавьте нужные таблицы
]

export_dir = "/path/to/export"

for table in tables:
    name = table.split(".")[-1]
    print(f"Экспорт {table}...")
    df = spark.sql(f"SELECT * FROM {table}")
    
    # Вариант 1: Parquet (рекомендуется — быстрее, компактнее)
    df.coalesce(1).write.mode("overwrite").parquet(f"{export_dir}/{name}.parquet")
    
    # Вариант 2: CSV (если Parquet недоступен)
    # df.toPandas().to_csv(f"{export_dir}/{name}.csv", index=False)

print("Готово! Скопируйте файлы в папку data/ пакета.")
""")
        sys.exit(1)
    
    print(f"📂 Найдено: {len(parquet_files)} parquet-файлов, "
          f"{len(csv_files)} csv-файлов, {len(parquet_dirs)} parquet-директорий")
    print()
    
    # Создаём / открываем DuckDB
    conn = duckdb.connect(str(db_path))
    
    # Создаём схему если нужно
    if schema != "main":
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    
    loaded = 0
    
    # Загружаем одиночные Parquet-файлы
    for pf in parquet_files:
        table_name = pf.stem  # users.parquet → users
        fqn = f"{schema}.{table_name}" if schema != "main" else table_name
        print(f"  📥 {pf.name} → {fqn}")
        try:
            conn.execute(f'CREATE OR REPLACE TABLE {fqn} AS SELECT * FROM read_parquet(\'{pf}\')')
            count = conn.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]
            cols = conn.execute(f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table_name}'").fetchone()[0]
            print(f"     ✅ {count} строк, {cols} колонок")
            loaded += 1
        except Exception as e:
            print(f"     ❌ Ошибка: {e}")
    
    # Загружаем Parquet-директории (Spark output)
    for pd in parquet_dirs:
        table_name = pd.name
        fqn = f"{schema}.{table_name}" if schema != "main" else table_name
        glob_path = str(pd / "*.parquet")
        print(f"  📥 {pd.name}/ (Spark parquet) → {fqn}")
        try:
            conn.execute(f"CREATE OR REPLACE TABLE {fqn} AS SELECT * FROM read_parquet('{glob_path}')")
            count = conn.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]
            cols = conn.execute(f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table_name}'").fetchone()[0]
            print(f"     ✅ {count} строк, {cols} колонок")
            loaded += 1
        except Exception as e:
            print(f"     ❌ Ошибка: {e}")
    
    # Загружаем CSV
    for cf in csv_files:
        table_name = cf.stem
        fqn = f"{schema}.{table_name}" if schema != "main" else table_name
        print(f"  📥 {cf.name} → {fqn}")
        try:
            conn.execute(f"CREATE OR REPLACE TABLE {fqn} AS SELECT * FROM read_csv_auto('{cf}')")
            count = conn.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]
            cols = conn.execute(f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table_name}'").fetchone()[0]
            print(f"     ✅ {count} строк, {cols} колонок")
            loaded += 1
        except Exception as e:
            print(f"     ❌ Ошибка: {e}")
    
    # Итог
    if schema != "main":
        all_tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = ? AND table_type = 'BASE TABLE' ORDER BY table_name",
            [schema]
        ).fetchall()
    else:
        all_tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' ORDER BY table_name"
        ).fetchall()
    
    conn.close()
    
    print()
    print("=" * 60)
    print(f"  ✅ ГОТОВО! Загружено таблиц: {loaded}")
    print("=" * 60)
    print(f"""
DuckDB-файл: {db_path} ({os.path.getsize(db_path) / 1024 / 1024:.1f} MB)
Схема: {schema}
Таблицы: {', '.join(t[0] for t in all_tables)}

Следующие шаги:
  1. Убедитесь что config.yml настроен:
     database:
       driver: "duckdb"
       path: "{db_path}"
       schema: "{schema}"

  2. Настройте Cube для DuckDB (см. cube.env.example)

  3. Запустите: python 01_data_loader.py
     (или: python 01_data_loader.py --source duckdb)
""")


def main():
    parser = argparse.ArgumentParser(
        description="Загрузка Parquet/CSV в DuckDB для Cube",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python 00_load_duckdb.py --data-dir ./data
  python 00_load_duckdb.py --data-dir /export/gp_tables --db ./analytics.duckdb
  python 00_load_duckdb.py --data-dir ./data --schema dbo
        """
    )
    parser.add_argument("--data-dir", default="./data",
                        help="Директория с Parquet/CSV файлами (default: ./data)")
    parser.add_argument("--db", default="./data.duckdb",
                        help="Путь к DuckDB-файлу (default: ./data.duckdb)")
    parser.add_argument("--schema", default="main",
                        help="Схема в DuckDB (default: main)")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  ЗАГРУЗКА ДАННЫХ В DUCKDB")
    print("  Parquet/CSV → DuckDB → Cube")
    print("=" * 60)
    print()
    
    load_files_to_duckdb(args.data_dir, args.db, args.schema)


if __name__ == "__main__":
    main()
