from typing import Annotated, Any

from pydantic import BaseModel, Field

from ta_backend_core.assistant.agents.toolkits.registry import tool
from ta_backend_core.assistant.utils import logger

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
Before using these tools, configure the MySQL connection-related environment variables.

Required environment variables:
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`

Optional environment variables:
- `MYSQL_DATABASE_DESCRIPTION`: database description, appended to the tool description to help the model understand table semantics

Please complete the above configuration in the backend runtime environment before using these MySQL tools.
""".strip()


def get_connection_manager() -> MySQLConnectionManager:
    """Get the global connection manager"""
    global _connection_manager
    if _connection_manager is None:
        import os

        # Read MySQL configuration from environment variables
        mysql_config = {
            "host": os.getenv("MYSQL_HOST"),
            "user": os.getenv("MYSQL_USER"),
            "password": os.getenv("MYSQL_PASSWORD"),
            "database": os.getenv("MYSQL_DATABASE"),
            "port": int(os.getenv("MYSQL_PORT") or "3306"),
            "charset": "utf8mb4",
            "description": os.getenv("MYSQL_DATABASE_DESCRIPTION") or "Default MySQL database",
        }
        # Validate configuration completeness
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
    """[List table names and descriptions] Get all table names in the database

    This tool lists all table names in the current database to help you understand the database structure.
    """
    try:
        conn_manager = get_connection_manager()

        with conn_manager.get_cursor() as cursor:
            # Get table names
            cursor.execute("SHOW TABLES")
            logger.debug("Executed `SHOW TABLES` query")
            tables = cursor.fetchall()

            if not tables:
                return "No tables were found in the database"

            # Extract table names
            table_names = []
            for table in tables:
                table_name = list(table.values())[0]
                table_names.append(table_name)

            # Get row count information for each table
            # table_info = []
            # for table_name in table_names:
            #     try:
            #         cursor.execute(f"SELECT COUNT(*) as count FROM `{table_name}`")
            #         logger.debug(f"Executed `SELECT COUNT(*) FROM {table_name}` query")
            #         count_result = cursor.fetchone()
            #         row_count = count_result["count"]
            #         table_info.append(f"- {table_name} (about {row_count} rows)")
            #     except Exception:
            #         table_info.append(f"- {table_name} (unable to get row count)")

            all_table_names = "\n".join(table_names)
            result = f"Tables in the database:\n{all_table_names}"
            if db_note := conn_manager.config.get("description"):
                result = f"Database description: {db_note}\n\n" + result
            logger.info(f"Retrieved {len(table_names)} tables from database")
            return result

    except Exception as e:
        error_msg = f"Failed to get table names: {str(e)}"
        logger.error(error_msg)
        return error_msg


class TableDescribeModel(BaseModel):
    """Input model for retrieving table structure"""

    table_name: str = Field(description="Table name to query", example="users")


@tool(
    category="mysql",
    tags=["database", "schema"],
    display_name="Describe MySQL Table Structure",
    config_guide=MYSQL_CONFIG_GUIDE,
    name_or_callable="mysql_describe_table",
    args_schema=TableDescribeModel,
)
def mysql_describe_table(table_name: Annotated[str, "Table name to query"]) -> str:
    """[Describe table] Get detailed structure information for a specified table

    This tool is used to view field information, data types, NULL allowance, default values, key types, and more.
    It helps you understand the table structure so you can write correct SQL queries.
    """
    try:
        # Validate table name safety
        if not MySQLSecurityChecker.validate_table_name(table_name):
            return "The table name contains invalid characters; please check the table name"

        conn_manager = get_connection_manager()

        with conn_manager.get_cursor() as cursor:
            # Get table structure
            cursor.execute(f"DESCRIBE `{table_name}`")
            columns = cursor.fetchall()

            if not columns:
                return f"Table {table_name} does not exist or has no fields"

            # Get column comment information
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
                        column_comments[column_name] = row.get("COLUMN_COMMENT") or ""
            except Exception as e:
                logger.warning(f"Failed to fetch column comments for table {table_name}: {e}")

            # Format output
            result = f"Structure of table `{table_name}`:\n\n"
            result += "Field\t\tType\t\tNULL\tKey\tDefault\t\tExtra\tComment\n"
            result += "-" * 80 + "\n"

            for col in columns:
                field = col["Field"] or ""
                type_str = col["Type"] or ""
                null_str = col["Null"] or ""
                key_str = col["Key"] or ""
                default_str = col.get("Default") or ""
                extra_str = col.get("Extra") or ""
                comment_str = column_comments.get(field, "")

                # Format output
                result += (
                    f"{field:<16}\t{type_str:<16}\t{null_str:<8}\t{key_str:<4}\t"
                    f"{default_str:<16}\t{extra_str:<16}\t{comment_str}\n"
                )

            # Get index information
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
                logger.warning(f"Failed to get index info for table {table_name}: {e}")

            logger.info(f"Retrieved structure for table {table_name}")
            return result

    except Exception as e:
        error_msg = f"Failed to get structure for table {table_name}: {str(e)}"
        logger.error(error_msg)
        return error_msg


class QueryModel(BaseModel):
    """Input model for executing SQL queries"""

    sql: str = Field(description="SQL query to execute (SELECT statements only)", example="SELECT * FROM users WHERE id = 1")
    timeout: int | None = Field(default=60, description="Query timeout in seconds, default 60 seconds, maximum 600 seconds", ge=1, le=600)


@tool(
    category="mysql",
    tags=["database", "sql"],
    display_name="Execute MySQL Query",
    config_guide=MYSQL_CONFIG_GUIDE,
    name_or_callable="mysql_query",
    args_schema=QueryModel,
)
def mysql_query(
    sql: Annotated[str, "SQL query to execute (SELECT statements only)"],
    timeout: Annotated[int | None, "Query timeout in seconds, default 60 seconds, maximum 600 seconds"] = 60,
) -> str:
    """[Execute SQL query] Execute a read-only SQL query

    This tool executes SQL queries and returns the results. It supports complex SELECT queries, including JOINs and GROUP BY.
    Note: only query operations are allowed; data cannot be modified.

    Args:
    - sql: SQL query
    - timeout: Query timeout (prevents long-running queries)
    """
    try:
        # Validate SQL safety
        if not MySQLSecurityChecker.validate_sql(sql):
            return "The SQL statement contains unsafe operations or a possible injection attack; please check the SQL statement"

        if not MySQLSecurityChecker.validate_timeout(timeout):
            return "The timeout parameter must be between 1 and 600"

        conn_manager = get_connection_manager()
        connection = conn_manager.get_connection()

        effective_timeout = timeout or 60
        try:
            result = execute_query_with_timeout(connection, sql, timeout=effective_timeout)
        except QueryTimeoutError as timeout_error:
            logger.error(f"MySQL query timed out after {effective_timeout} seconds: {timeout_error}")
            raise
        except Exception:
            conn_manager.invalidate_connection()
            raise

        if not result:
            return "Query executed successfully, but no data was returned"

        # Limit result size
        limited_result = limit_result_size(result, max_chars=10000)

        # Check whether the result was truncated
        if len(limited_result) < len(result):
            warning = f"\n\n⚠️ Warning: the query result is too large; only the first {len(limited_result)} rows are shown (out of {len(result)} rows).\n"
            warning += "Consider using more precise query conditions or a LIMIT clause to reduce the returned data volume."
        else:
            warning = ""

        # Format output
        if limited_result:
            # Get column names
            columns = list(limited_result[0].keys())

            # Calculate the maximum width of each column
            col_widths = {}
            for col in columns:
                col_widths[col] = max(len(str(col)), max(len(str(row.get(col, ""))) for row in limited_result))
                col_widths[col] = min(col_widths[col], 50)  # Limit maximum width

            # Build header
            header = "| " + " | ".join(f"{col:<{col_widths[col]}}" for col in columns) + " |"
            separator = "|" + "|".join("-" * (col_widths[col] + 2) for col in columns) + "|"

            # Build data rows
            rows = []
            for row in limited_result:
                row_str = "| " + " | ".join(f"{str(row.get(col, '')):<{col_widths[col]}}" for col in columns) + " |"
                rows.append(row_str)

            result_str = f"Query results ({len(limited_result)} rows total):\n\n"
            result_str += header + "\n" + separator + "\n"
            result_str += "\n".join(rows[:50])  # Show at most 50 rows

            if len(rows) > 50:
                result_str += f"\n\n... {len(rows) - 50} more rows not shown ..."

            result_str += warning

            logger.info(f"Query executed successfully, returned {len(limited_result)} rows")
            return result_str

        return "Query executed successfully, but no data was returned"

    except Exception as e:
        error_msg = f"SQL query execution failed: {str(e)}\n\n{sql}"

        # Provide more useful error messages
        if "timeout" in str(e).lower():
            error_msg += "\n\n💡 Suggestion: the query timed out. Try the following:\n"
            error_msg += "1. Reduce the amount of data queried (use WHERE filters)\n"
            error_msg += "2. Use a LIMIT clause to restrict the number of returned rows\n"
            error_msg += "3. Increase the timeout value (maximum 600 seconds)"
        elif "table" in str(e).lower() and "doesn't exist" in str(e).lower():
            error_msg += "\n\n💡 Suggestion: the table does not exist. Use mysql_list_tables to view available table names"
        elif "column" in str(e).lower() and "doesn't exist" in str(e).lower():
            error_msg += "\n\n💡 Suggestion: the column does not exist. Use mysql_describe_table to view the table structure"
        elif "not enough arguments for format string" in str(e).lower():
            error_msg += (
                "\n\n💡 Suggestion: the percent sign (%) in SQL is treated as a parameter placeholder."
                " If you need to match text containing a percent sign, escape it as double percent (%%) or use a parameterized query."
            )

        logger.error(error_msg)
        return error_msg


def _get_db_description() -> str:
    """Get the database description"""
    import os

    return os.getenv("MYSQL_DATABASE_DESCRIPTION") or ""


# Track whether the description has already been injected to avoid duplication
_db_description_injected: bool = False


def _inject_db_description(tools: list[Any]) -> None:
    """Inject the database description into tool descriptions"""
    global _db_description_injected
    if _db_description_injected:
        return

    db_desc = _get_db_description()
    if not db_desc:
        return

    for _tool in tools:
        if hasattr(_tool, "description"):
            # Append the database description to the end of the tool description
            _tool.description = f"{_tool.description}\n\nCurrent database description: {db_desc}"

    _db_description_injected = True


def get_mysql_tools() -> list[Any]:
    """Get the MySQL tool list"""
    tools = [mysql_list_tables, mysql_describe_table, mysql_query]
    _inject_db_description(tools)
    return tools
