class MySQLToolError(Exception):
    """Base MySQL tool error"""

    pass


class MySQLConnectionError(MySQLToolError):
    """MySQL connection error"""

    pass


class MySQLQueryError(MySQLToolError):
    """MySQL query error"""

    pass


class MySQLSecurityError(MySQLToolError):
    """MySQL security error"""

    pass


class MySQLTimeoutError(MySQLToolError):
    """MySQL timeout error"""

    pass


class MySQLResultTooLargeError(MySQLToolError):
    """MySQL result too large error"""

    pass
