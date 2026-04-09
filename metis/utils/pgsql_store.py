from threading import Lock
from typing import Any, Optional

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor

from config import config


class PgJsonStore:
    _instance: Optional["PgJsonStore"] = None
    _instance_lock = Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "PgJsonStore":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, dsn: str = None) -> None:
        if getattr(self, "_initialized", False):
            return
        
        if dsn is None:
            raise ValueError("DSN must be provided for PgJsonStore initialization")

        self._dsn = dsn
        self._initialized = True

    def _get_connection(self):
        return psycopg2.connect(self._dsn)

    def _table_identifier(self, table_name: str) -> sql.Identifier:
        if not table_name:
            raise ValueError("table_name must not be empty")
        return sql.Identifier(table_name)
    
    def _execute(self, query: Any, params: Any = None, fetch: str | None = None) -> Any:
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                if fetch == "one":
                    return cursor.fetchone()
                if fetch == "all":
                    return cursor.fetchall()
                conn.commit()
                return cursor.rowcount

    def init_table(self, table_name: str = "sessions") -> None:
        """创建表和索引"""
        table = self._table_identifier(table_name)
        index = sql.Identifier(f"idx_{table_name}_data")

        create_table_sql = sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {table} (
                id VARCHAR(255) PRIMARY KEY,
                data JSONB NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        ).format(table=table)
        create_index_sql = sql.SQL(
            "CREATE INDEX IF NOT EXISTS {index} ON {table} USING GIN (data);"
        ).format(index=index, table=table)

        self._execute(create_table_sql)
        self._execute(create_index_sql)

    def upsert_session(self, table_name: str, session_id: str, data: dict) -> None:
        """写入/更新数据"""
        query = sql.SQL(
            """
            INSERT INTO {table} (id, data, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE
            SET data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP;
            """
        ).format(table=self._table_identifier(table_name))
        self._execute(query, (session_id, Json(data)))

    def get_session(self, table_name: str, session_id: str) -> Optional[dict]:
        """读取数据"""
        query = sql.SQL("SELECT data FROM {table} WHERE id = %s;").format(
            table=self._table_identifier(table_name)
        )
        result = self._execute(query, (session_id,), fetch="one")
        return result["data"] if result else None

    def list_sessions(self, table_name: str, limit: int = 100, offset: int = 0) -> list[dict]:
        """读取全部数据列表"""
        query = sql.SQL(
            """
            SELECT id, data, updated_at
            FROM {table}
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s;
            """
        ).format(table=self._table_identifier(table_name))
        return self._execute(query, (limit, offset), fetch="all")

    def find_sessions(self, table_name: str, filters: dict, limit: int = 100, offset: int = 0) -> list[dict]:
        """按 JSON 条件查找数据列表，filters 会使用 JSONB @> 做局部匹配"""
        query = sql.SQL(
            """
            SELECT id, data, updated_at
            FROM {table}
            WHERE data @> %s::jsonb
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s;
            """
        ).format(table=self._table_identifier(table_name))
        return self._execute(query, (Json(filters), limit, offset), fetch="all")

    def find_one_session(self, table_name: str, filters: dict) -> Optional[dict]:
        """按 JSON 条件查找单条数据"""
        query = sql.SQL(
            """
            SELECT id, data, updated_at
            FROM {table}
            WHERE data @> %s::jsonb
            ORDER BY updated_at DESC
            LIMIT 1;
            """
        ).format(table=self._table_identifier(table_name))
        return self._execute(query, (Json(filters),), fetch="one")

    def find_by_field(
        self,
        table_name: str,
        field_path: str,
        value: Any,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """按 JSON 中指定字段路径精确查找，如 user.name 或 profile.age"""
        path_parts = [part for part in field_path.split(".") if part]
        if not path_parts:
            raise ValueError("field_path must not be empty")

        query = sql.SQL(
            """
            SELECT id, data, updated_at
            FROM {table}
            WHERE data #> %s = %s::jsonb
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s;
            """
        ).format(table=self._table_identifier(table_name))
        return self._execute(query, (path_parts, Json(value), limit, offset), fetch="all")

    def count_sessions(self, table_name: str, filters: Optional[dict] = None) -> int:
        """统计满足条件的数据数量"""
        table = self._table_identifier(table_name)
        if filters:
            query = sql.SQL("SELECT COUNT(*) AS total FROM {table} WHERE data @> %s::jsonb;").format(
                table=table
            )
            result = self._execute(query, (Json(filters),), fetch="one")
        else:
            query = sql.SQL("SELECT COUNT(*) AS total FROM {table};").format(table=table)
            result = self._execute(query, fetch="one")
        return int(result["total"])

    def update_session_fields(self, table_name: str, session_id: str, patch_data: dict) -> Optional[dict]:
        """合并更新 JSON 字段"""
        query = sql.SQL(
            """
            UPDATE {table}
            SET data = data || %s::jsonb,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id, data, updated_at;
            """
        ).format(table=self._table_identifier(table_name))
        return self._execute(query, (Json(patch_data), session_id), fetch="one")

    def delete_session(self, table_name: str, session_id: str) -> bool:
        """按主键删除数据"""
        query = sql.SQL("DELETE FROM {table} WHERE id = %s;").format(
            table=self._table_identifier(table_name)
        )
        deleted_rows = self._execute(query, (session_id,))
        return deleted_rows > 0

    def delete_sessions(self, table_name: str, filters: dict) -> int:
        """按 JSON 条件批量删除数据"""
        query = sql.SQL("DELETE FROM {table} WHERE data @> %s::jsonb;").format(
            table=self._table_identifier(table_name)
        )
        return self._execute(query, (Json(filters),))
    

def get_pg_store() -> PgJsonStore:
    """获取PgJsonStore单例实例"""
    postgres_config = config.get("postgres")
    dsn = f"host={postgres_config['host']} port={postgres_config['port']} user={postgres_config['user']} password={postgres_config['password']} dbname={postgres_config['dbname']}"
    store = PgJsonStore(dsn)
    return store