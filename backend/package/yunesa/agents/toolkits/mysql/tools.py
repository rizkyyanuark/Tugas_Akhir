from typing import Annotated, Any

from pydantic import BaseModel, Field

from yunesa.agents.toolkits.registry import tool
from yunesa.utils import logger

from .connection import (
    MySQLConnectionManager,
    QueryTimeoutError,
    execute_query_with_timeout,
    limit_result_size,
)
from .exceptions import MySQLConnectionError
from .security import MySQLSecurityChecker

# Global connection manager instance
_connection_manager: MySQLConnectionManager | None = None

MYSQL_CONFIG_GUIDE = """
Before using these tools, configure MySQL connection environment variables.

Required environment variables:
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`

Optional environment variables:
- `MYSQL_DATABASE_DESCRIPTION`: database description appended to tool descriptions to help model understanding

Configure these variables in the backend runtime before using MySQL tools.
""".strip()


def get_connection_manager() -> MySQLConnectionManager:
    """Get global connection manager."""
    global _connection_manager
    if _connection_manager is None:
        import os

        # Read MySQL config from environment variables.
        mysql_config = {
            "host": os.getenv("MYSQL_HOST"),
            "user": os.getenv("MYSQL_USER"),
            "password": os.getenv("MYSQL_PASSWORD"),
            "database": os.getenv("MYSQL_DATABASE"),
            "port": int(os.getenv("MYSQL_PORT") or "3306"),
            "charset": "utf8mb4",
            "description": os.getenv("MYSQL_DATABASE_DESCRIPTION") or "default MySQL database",
        }
        # Validate required config keys.
        required_keys = ["host", "user", "password", "database"]
        for key in required_keys:
            if not mysql_config[key]:
                raise MySQLConnectionError(
                    f"MySQL configuration missing required key: {key}, please check your environment variables."
                )

        _connection_manager = MySQLConnectionManager(mysql_config)
    return _connection_manager


@tool(
    category="mysql",
    tags=["database", "query"],
    display_name="List MySQL Tables",
    config_guide=MYSQL_CONFIG_GUIDE,
    name_or_callable="mysql_list_tables",
)
def mysql_list_tables() -> str:
    """[List tables] Get all table names in the database.

    This tool lists all table names in the current database to help understand its structure.
    """
    try:
        conn_manager = get_connection_manager()

        with conn_manager.get_cursor() as cursor:
            # Get table names.
            cursor.execute("SHOW TABLES")
            logger.debug("Executed `SHOW TABLES` query")
            tables = cursor.fetchall()

            if not tables:
                return "No tables found in the database"

            # Extract table names.
            table_names = []
            for table in tables:
                table_name = list(table.values())[0]
                table_names.append(table_name)

            # Get row count per table.
            # table_info = []
            # for table_name in table_names:
            #     try:
            #         cursor.execute(f"SELECT COUNT(*) as count FROM `{table_name}`")
            #         logger.debug(f"Executed `SELECT COUNT(*) FROM {table_name}` query")
            #         count_result = cursor.fetchone()
            #         row_count = count_result["count"]
            #         table_info.append(f"- {table_name} (~{row_count} rows)")
            #     except Exception:
            #         table_info.append(f"- {table_name} (unable to get row count)")

            all_table_names = "\n".join(table_names)
            result = f"Tables in database:\n{all_table_names}"
            if db_note := conn_manager.config.get("description"):
                result = f"Database description: {db_note}\n\n" + result
            logger.info(f"Retrieved {len(table_names)} tables from database")
            return result

    except Exception as e:
        error_msg = f"Failed to get table names: {str(e)}"
        logger.error(error_msg)
        return error_msg


class TableDescribeModel(BaseModel):
    """Parameter model for describing table schema."""

    table_name: str = Field(
        description="Table name to inspect", example="users")


@tool(
    category="mysql",
    tags=["database", "schema"],
    display_name="Describe MySQL Table",
    config_guide=MYSQL_CONFIG_GUIDE,
    name_or_callable="mysql_describe_table",
    args_schema=TableDescribeModel,
)
def mysql_describe_table(table_name: Annotated[str, "Table name to describe"]) -> str:
    """[Describe table] Get detailed schema information of a specific table.

    This tool shows field info, data types, nullability, default values, key types, and more.
    It helps you understand schema structure and write correct SQL queries.
    """
    try:
        # Validate table-name safety.
        if not MySQLSecurityChecker.validate_table_name(table_name):
            return "Table name contains invalid characters. Please check table_name"

        conn_manager = get_connection_manager()

        with conn_manager.get_cursor() as cursor:
            # Get table schema.
            cursor.execute(f"DESCRIBE `{table_name}`")
            columns = cursor.fetchall()

            if not columns:
                return f"Table {table_name} does not exist or has no fields"

            # Get column comments.
            column_comments: dict[str, str] = {}
            try:
                cursor.execute(
                    """
                    SELECT COLUMN_NAME, COLUMN_COMMENT
                    FROM information_schema.COLUMNS
                    WHERE TABLE_NAME = %s AND TABLE_SCHEMA = %s
                    """,
                    (table_name, conn_manager.database_name),
                )
                comment_rows = cursor.fetchall()
                for row in comment_rows:
                    column_name = row.get("COLUMN_NAME")
                    if column_name:
                        column_comments[column_name] = row.get(
                            "COLUMN_COMMENT") or ""
            except Exception as e:
                logger.warning(
                    f"Failed to fetch column comments for table {table_name}: {e}")

            # Format output.
            result = f"Schema for table `{table_name}`:\n\n"
            result += "Field\t\tType\t\tNull\tKey\tDefault\t\tExtra\tComment\n"
            result += "-" * 80 + "\n"

            for col in columns:
                field = col["Field"] or ""
                type_str = col["Type"] or ""
                null_str = col["Null"] or ""
                key_str = col["Key"] or ""
                default_str = col.get("Default") or ""
                extra_str = col.get("Extra") or ""
                comment_str = column_comments.get(field, "")

                # Format output.
                result += (
                    f"{field:<16}\t{type_str:<16}\t{null_str:<8}\t{key_str:<4}\t"
                    f"{default_str:<16}\t{extra_str:<16}\t{comment_str}\n"
                )

            # Get index information.
            try:
                cursor.execute(f"SHOW INDEX FROM `{table_name}`")
                indexes = cursor.fetchall()

                if indexes:
                    result += "\nIndex information:\n"
                    index_dict = {}
                    for idx in indexes:
                        key_name = idx["Key_name"]
                        if key_name not in index_dict:
                            index_dict[key_name] = []
                        index_dict[key_name].append(idx["Column_name"])

                    for key_name, columns in index_dict.items():
                        result += f"- {key_name}: {', '.join(columns)}\n"
            except Exception as e:
                logger.warning(
                    f"Failed to get index info for table {table_name}: {e}")

            logger.info(f"Retrieved structure for table {table_name}")
            return result

    except Exception as e:
        error_msg = f"Failed to get schema for table {table_name}: {str(e)}"
        logger.error(error_msg)
        return error_msg


class QueryModel(BaseModel):
    """Parameter model for SQL query execution."""

    sql: str = Field(description="SQL query to execute (SELECT-only)",
                     example="SELECT * FROM users WHERE id = 1")
    timeout: int | None = Field(
        default=60, description="Query timeout in seconds, default 60, max 600", ge=1, le=600)


@tool(
    category="mysql",
    tags=["database", "SQL"],
    display_name="Execute MySQL Query",
    config_guide=MYSQL_CONFIG_GUIDE,
    name_or_callable="mysql_query",
    args_schema=QueryModel,
)
def mysql_query(
    sql: Annotated[str, "SQL query to execute (SELECT-only)"],
    timeout: Annotated[int | None,
                       "Query timeout in seconds, default 60, max 600"] = 60,
) -> str:
    """[Execute SQL query] Execute a read-only SQL query.

    This tool executes SQL queries and returns results.
    Supports complex SELECT queries including JOIN and GROUP BY.
    Note: query-only operations are allowed; data modification is not allowed.

    Parameters:
    - sql: SQL query statement
    - timeout: query timeout (to avoid long-running queries)
    """
    try:
        # Validate SQL safety.
        if not MySQLSecurityChecker.validate_sql(sql):
            return "SQL contains unsafe operations or possible injection patterns. Please review the query"

        if not MySQLSecurityChecker.validate_timeout(timeout):
            return "timeout must be between 1 and 600 seconds"

        conn_manager = get_connection_manager()
        connection = conn_manager.get_connection()

        effective_timeout = timeout or 60
        try:
            result = execute_query_with_timeout(
                connection, sql, timeout=effective_timeout)
        except QueryTimeoutError as timeout_error:
            logger.error(
                f"MySQL query timed out after {effective_timeout} seconds: {timeout_error}")
            raise
        except Exception:
            conn_manager.invalidate_connection()
            raise

        if not result:
            return "Query executed successfully, but returned no results"

        # Limit result size.
        limited_result = limit_result_size(result, max_chars=10000)

        # Check whether result has been truncated.
        if len(limited_result) < len(result):
            warning = (
                f"\n\nWarning: query result is too large; only first {len(limited_result)} rows are shown "
                f"(total {len(result)} rows).\n"
            )
            warning += "Use more precise filters or a LIMIT clause to reduce returned data."
        else:
            warning = ""

        # Format output.
        if limited_result:
            # Get column names.
            columns = list(limited_result[0].keys())

            # Calculate max width per column.
            col_widths = {}
            for col in columns:
                col_widths[col] = max(len(str(col)), max(
                    len(str(row.get(col, ""))) for row in limited_result))
                col_widths[col] = min(col_widths[col], 50)  # Limit max width.

            # Build table header.
            header = "| " + \
                " | ".join(
                    f"{col:<{col_widths[col]}}" for col in columns) + " |"
            separator = "|" + \
                "|".join("-" * (col_widths[col] + 2) for col in columns) + "|"

            # Build data rows.
            rows = []
            for row in limited_result:
                row_str = "| " + \
                    " | ".join(
                        f"{str(row.get(col, '')):<{col_widths[col]}}" for col in columns) + " |"
                rows.append(row_str)

            result_str = f"Query result ({len(limited_result)} rows):\n\n"
            result_str += header + "\n" + separator + "\n"
            result_str += "\n".join(rows[:50])  # Show at most 50 rows.

            if len(rows) > 50:
                result_str += f"\n\n... {len(rows) - 50} more rows not shown ..."

            result_str += warning

            logger.info(
                f"Query executed successfully, returned {len(limited_result)} rows")
            return result_str

        return "Query executed successfully, but returned empty data"

    except Exception as e:
        error_msg = f"SQL query execution failed: {str(e)}\n\n{sql}"

        # Provide more helpful error hints.
        if "timeout" in str(e).lower():
            error_msg += "\n\nSuggestion: query timed out. Try:\n"
            error_msg += "1. Reduce data volume with WHERE filters\n"
            error_msg += "2. Use LIMIT to reduce returned rows\n"
            error_msg += "3. Increase timeout value (max 600 seconds)"
        elif "table" in str(e).lower() and "doesn't exist" in str(e).lower():
            error_msg += "\n\nSuggestion: table does not exist. Use mysql_list_tables to view available tables"
        elif "column" in str(e).lower() and "doesn't exist" in str(e).lower():
            error_msg += "\n\nSuggestion: column does not exist. Use mysql_describe_table to inspect table schema"
        elif "not enough arguments for format string" in str(e).lower():
            error_msg += (
                "\n\nSuggestion: percent signs (%) in SQL are treated as format placeholders."
                " If you need literal percent matching, use double percent (%%) or parameterized queries."
            )

        logger.error(error_msg)
        return error_msg


def _get_db_description() -> str:
    """Get database description."""
    import os

    return os.getenv("MYSQL_DATABASE_DESCRIPTION") or ""


# Track whether description has been injected to avoid duplication.
_db_description_injected: bool = False


def _inject_db_description(tools: list[Any]) -> None:
    """Inject database description into tool descriptions."""
    global _db_description_injected
    if _db_description_injected:
        return

    db_desc = _get_db_description()
    if not db_desc:
        return

    for _tool in tools:
        if hasattr(_tool, "description"):
            # Append database description at the end.
            _tool.description = f"{_tool.description}\n\nCurrent database description: {db_desc}"

    _db_description_injected = True


def get_mysql_tools() -> list[Any]:
    """Get MySQL tool list."""
    tools = [mysql_list_tables, mysql_describe_table, mysql_query]
    _inject_db_description(tools)
    return tools
