class MySQLToolError(Exception):
    """Base exception for MySQL tools."""

    pass


class MySQLConnectionError(MySQLToolError):
    """MySQL connection exception."""

    pass


class MySQLQueryError(MySQLToolError):
    """MySQL query exception."""

    pass


class MySQLSecurityError(MySQLToolError):
    """MySQL security exception."""

    pass


class MySQLTimeoutError(MySQLToolError):
    """MySQL timeout exception."""

    pass


class MySQLResultTooLargeError(MySQLToolError):
    """MySQL result too large exception."""

    pass
