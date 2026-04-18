import concurrent.futures
import threading
import time
from contextlib import contextmanager
from typing import Any

import pymysql
from pymysql import MySQLError
from pymysql.cursors import DictCursor

from yunesa.utils import logger


class MySQLConnectionManager:
    """MySQL database connection manager."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.connection = None
        self._lock = threading.Lock()
        self.last_connection_time = 0
        self.max_connection_age = 3600  # Reconnect after 1 hour.

    def _get_connection(self) -> pymysql.Connection:
        """Get database connection."""
        current_time = time.time()

        # Check whether connection is expired or disconnected.
        if (
            self.connection is None
            or not self.connection.open
            or current_time - self.last_connection_time > self.max_connection_age
        ):
            with self._lock:
                # Double-check in lock.
                if (
                    self.connection is None
                    or not self.connection.open
                    or current_time - self.last_connection_time > self.max_connection_age
                ):
                    # Close old connection.
                    if self.connection and self.connection.open:
                        try:
                            self.connection.close()
                        except Exception as _:
                            pass

                    # Create new connection.
                    self.connection = self._create_connection()
                    self.last_connection_time = current_time

        return self.connection

    def _create_connection(self) -> pymysql.Connection:
        """Create a new database connection."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                connection = pymysql.connect(
                    host=self.config["host"],
                    user=self.config["user"],
                    password=self.config["password"],
                    database=self.config["database"],
                    port=self.config["port"],
                    charset=self.config.get("charset", "utf8mb4"),
                    cursorclass=DictCursor,
                    connect_timeout=10,
                    read_timeout=60,  # Increase read timeout.
                    write_timeout=30,
                    autocommit=True,  # Enable autocommit.
                )
                logger.info(
                    f"MySQL connection established successfully (attempt {attempt + 1})")
                return connection

            except MySQLError as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)  # Exponential backoff.
                else:
                    logger.error(
                        f"Failed to connect to MySQL after {max_retries} attempts: {e}")
                    raise ConnectionError(f"MySQL connection failed: {e}")

    def test_connection(self) -> bool:
        """Test whether connection is valid."""
        try:
            if self.connection and self.connection.open:
                # Execute a simple query to validate connection.
                with self.connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                return True
        except Exception as _:
            pass
        return False

    def _invalidate_connection(self, connection: pymysql.Connection | None = None):
        """Invalidate and clean up a broken connection."""
        try:
            if connection:
                connection.close()
        except Exception:
            pass
        finally:
            self.connection = None

    @contextmanager
    def get_cursor(self):
        """Context manager for obtaining a database cursor."""
        max_retries = 2
        cursor = None
        connection = None
        last_error: Exception | None = None

        # Ensure cursor acquisition succeeds before yielding to caller.
        for attempt in range(max_retries):
            try:
                connection = self._get_connection()
                cursor = connection.cursor()
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Failed to acquire cursor (attempt {attempt + 1}): {e}")
                self._invalidate_connection(connection)
                cursor = None
                connection = None
                if attempt == max_retries - 1:
                    raise e
                time.sleep(1)

        if cursor is None or connection is None:
            raise last_error or ConnectionError(
                "Unable to acquire MySQL cursor")

        try:
            yield cursor
            connection.commit()
        except Exception as e:
            try:
                connection.rollback()
            except Exception:
                pass

            # Mark connection invalid and rebuild on next acquisition.
            if "MySQL" in str(e) or "connection" in str(e).lower():
                logger.warning(
                    f"MySQL connection error encountered, invalidating connection: {e}")
                self._invalidate_connection(connection)

            raise
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass

    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.info("MySQL connection closed")

    def get_connection(self) -> pymysql.Connection:
        """Public connection getter."""
        return self._get_connection()

    def invalidate_connection(self):
        """Manually invalidate current connection."""
        self._invalidate_connection(self.connection)

    @property
    def database_name(self) -> str:
        """Return configured database name."""
        return self.config["database"]


class QueryTimeoutError(Exception):
    """Query timeout exception."""

    pass


class QueryResultTooLargeError(Exception):
    """Query result too large exception."""

    pass


def execute_query_with_timeout(connection: pymysql.Connection, sql: str, params: tuple = None, timeout: int = 10):
    """Use a thread pool to enforce timeout and avoid signal-related generator issues."""

    def query_worker():
        """Query worker executed in a separate thread."""
        cursor = connection.cursor(DictCursor)
        try:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
            result = cursor.fetchall()
            return result
        finally:
            cursor.close()

    # Execute query in thread pool with timeout.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(query_worker)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # Attempt to cancel task.
            future.cancel()
            raise QueryTimeoutError(f"Query timeout after {timeout} seconds")


def limit_result_size(result: list, max_chars: int = 10000) -> list:
    """Limit result size by total character count."""
    if not result:
        return result

    # Calculate character size of full result.
    result_str = str(result)
    if len(result_str) > max_chars:
        # Return partial result when output is too large.
        limited_result = []
        current_chars = 0
        for row in result:
            row_str = str(row)
            if current_chars + len(row_str) > max_chars:
                break
            limited_result.append(row)
            current_chars += len(row_str)

        # Log warning.
        logger.warning(
            f"Query result truncated from {len(result)} to {len(limited_result)} rows due to size limit")
        return limited_result

    return result
