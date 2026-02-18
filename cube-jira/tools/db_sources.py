"""
Источники данных на базе SQLAlchemy: Greenplum и Hive с поддержкой Kerberos.
Единый интерфейс: get_tables, get_columns, get_foreign_keys, get_primary_key,
get_sample_data, get_row_count, close.
"""

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine
from typing import List, Any


def _ensure_kerberos_ticket(config_db: dict) -> None:
    """При включённом Kerberos создаёт тикет и устанавливает KRB5CCNAME. Пути без resolve — укажите абсолютные."""
    krb = config_db.get("kerberos") or {}
    if not krb.get("enabled"):
        return
    username = krb.get("username") or config_db.get("user", "")
    password = krb.get("password") or config_db.get("password", "")
    ticket_path = krb.get("ticket_path")
    krb5_config_path = krb.get("krb5_config_path", "krb5.conf")
    if not username or not password:
        raise ValueError("kerberos.enabled=true требует kerberos.username и kerberos.password (или database.user/database.password)")
    if not ticket_path:
        raise ValueError("kerberos.ticket_path обязателен — укажите абсолютный путь к файлу тикета")
    from kerberos_auth import get_or_create_kerberos_ticket, set_kerberos_env
    path = get_or_create_kerberos_ticket(
        username=username,
        password=password,
        ticket_path=ticket_path,
        krb5_config_path=krb5_config_path,
    )
    set_kerberos_env(path, krb5_config_path)


def _create_greenplum_engine(config: dict) -> Engine:
    """Движок SQLAlchemy для Greenplum (PostgreSQL-совместимый). С поддержкой Kerberos."""
    db = config["database"]
    host = db.get("host", "localhost")
    port = int(db.get("port", 5432))
    name = db.get("name", "")
    user = db.get("user", "")
    password = db.get("password", "")
    krb = db.get("kerberos") or {}
    use_kerberos = krb.get("enabled", False)

    # URL без логина — все аргументы в connect_args для единообразия
    url = f"postgresql+psycopg2://{host}:{port}/{name}"
    connect_args = {
        "user": user.replace("_omega-sbrf-ru", ""),
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5,
     }
    
    if use_kerberos:
        _ensure_kerberos_ticket(db)
        # GSSAPI: пароль не передаём
        connect_args["password"] = ""
    else:
        connect_args["password"] = password or ""

    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


def _create_hive_engine(config: dict) -> Engine:
    """Движок SQLAlchemy для Hive через PyHive. С поддержкой Kerberos."""
    db = config["database"]
    host = db.get("host", "localhost")
    port = int(db.get("port", 10000))
    schema = db.get("schema", "default")
    user = db.get("user", "")
    password = db.get("password", "")
    krb = db.get("kerberos") or {}
    use_kerberos = krb.get("enabled", True)

    # URL уже несёт host, port, schema (database); в connect_args только отличительные параметры
    url = f"hive://{host}:{port}/{schema}"

    connect_args = {}
    if use_kerberos:
        _ensure_kerberos_ticket(db)
        username = (user or krb.get("username", "")).replace("_omega-sbrf-ru", "")
        connect_args["username"] = username
        connect_args["auth"] = "KERBEROS"
        connect_args["kerberos_service_name"] = krb.get("kerberos_service_name", "hive")
    else:
        connect_args["username"] = user or ""
        connect_args["password"] = password or ""

    try:
        from pyhive import sqlalchemy_hive  # noqa: F401
    except ImportError:
        raise ImportError("Для Hive установите: pip install 'pyhive[hive]'")

    return create_engine(url, connect_args=connect_args, pool_pre_ping=False)


def _quoted_full_table(engine: Engine, schema: str, table_name: str) -> str:
    """Возвращает полное имя таблицы в кавычках для данного диалекта."""
    prep = engine.dialect.identifier_preparer
    q = prep.quote
    if schema and getattr(prep, "quote_schema", None):
        return f"{prep.quote_schema(schema)}.{q(table_name)}"
    if schema:
        return f"{q(schema)}.{q(table_name)}"
    return q(table_name)


class SQLAlchemySource:
    """Общий источник на базе SQLAlchemy engine. Работает с PostgreSQL/Greenplum и Hive."""

    def __init__(self, engine: Engine, schema: str):
        self.engine = engine
        self.schema = schema

    def get_tables(self):
        insp = inspect(self.engine)
        return insp.get_table_names(self.schema)

    def get_columns(self, table_name: str):
        insp = inspect(self.engine)
        cols = insp.get_columns(table_name, self.schema)
        return [
            {
                "name": c["name"],
                "data_type": str(c["type"]) if c.get("type") else "string",
                "nullable": c.get("nullable", True),
                "default": c.get("default"),
                "max_length": getattr(c.get("type"), "length", None),
            }
            for c in cols
        ]

    def get_foreign_keys(self, table_name: str):
        insp = inspect(self.engine)
        fks = insp.get_foreign_keys(table_name, self.schema)
        return [
            {
                "column": fk["constrained_columns"][0] if fk.get("constrained_columns") else None,
                "foreign_table": fk.get("referred_table"),
                "foreign_column": (fk.get("referred_columns") or [None])[0],
            }
            for fk in fks
            if fk.get("constrained_columns")
        ]

    def get_primary_key(self, table_name: str):
        insp = inspect(self.engine)
        pk = insp.get_pk_constraint(table_name, self.schema)
        if pk and pk.get("constrained_columns"):
            return pk["constrained_columns"][0]
        return "id"

    def get_sample_data(self, table_name: str, limit: int = 5):
        full = _quoted_full_table(self.engine, self.schema, table_name)
        with self.engine.connect() as conn:
            try:
                r = conn.execute(text(f"SELECT * FROM {full} LIMIT :lim"), {"lim": limit})
                columns = list(r.keys())
                rows = r.fetchall()
                return columns, [tuple(row) for row in rows]
            except Exception:
                return [], []

    def get_row_count(self, table_name: str):
        full = _quoted_full_table(self.engine, self.schema, table_name)
        with self.engine.connect() as conn:
            r = conn.execute(text(f"SELECT COUNT(*) FROM {full}"))
            return r.scalar() or 0

    def close(self):
        self.engine.dispose()
        
    def execute(self, sql: str, params: List[Any]) -> List[List[Any]]:
        import re
        
        def convert_dollar_to_percent(sql: str) -> str:
            """Конвертирует $1, $2... в %s для psycopg2"""
            return re.sub(r'\$(\d+)', r'%s', sql)
        
        raw_conn = self.engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            try:
                cursor.execute(convert_dollar_to_percent(sql), params)
                
                keys = [desc[0] for desc in cursor.description]
                data = cursor.fetchall()
                
            finally:
                cursor.close()
        finally:
            raw_conn.close()

        return [
            {
                key: value for key, value in zip(keys, row)
            } for row in data
        ]


class GreenplumSource(SQLAlchemySource):
    """Источник Greenplum (SQLAlchemy + при необходимости Kerberos)."""

    def __init__(self, config: dict):
        engine = _create_greenplum_engine(config)
        schema = config.get("database", {}).get("schema", "public")
        super().__init__(engine, schema)
        print(f"✅ Greenplum (SQLAlchemy): {config['database'].get('host')} (schema={self.schema})")
        
    def get_tables(self):
        with self.engine.connect() as conn:
            res = conn.execute(text(f"""
            WITH ver AS (
                SELECT role_name
                FROM information_schema.enabled_roles
            ),
            
            vtp AS (
                SELECT grantee, table_schema, table_name
                FROM information_schema.table_privileges
                WHERE privilege_type = 'SELECT'
            )
            
            SELECT table_schema, table_name
            FROM vtp
            JOIN ver ON vtp.grantee = ver.role_name
            WHERE table_schema = '{self.schema}'
            """)).fetchall()
            
        return [i[1] for i in res]


class HiveSource(SQLAlchemySource):
    """Источник Hive (SQLAlchemy/PyHive + Kerberos)."""

    def __init__(self, config: dict):
        engine = _create_hive_engine(config)
        schema = config.get("database", {}).get("schema", "default")
        super().__init__(engine, schema)
        print(f"✅ Hive (SQLAlchemy): {config['database'].get('host')} (schema={self.schema})")
