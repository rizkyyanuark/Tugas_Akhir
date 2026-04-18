import re


class MySQLSecurityChecker:
    """Security checker for MySQL queries."""

    # Allowed SQL operations
    ALLOWED_OPERATIONS = {"SELECT", "SHOW", "DESCRIBE", "EXPLAIN"}

    # Dangerous keywords
    DANGEROUS_KEYWORDS = {
        "DROP",
        "DELETE",
        "UPDATE",
        "INSERT",
        "CREATE",
        "ALTER",
        "TRUNCATE",
        "REPLACE",
        "LOAD",
        "GRANT",
        "REVOKE",
        "SET",
        "COMMIT",
        "ROLLBACK",
        "UNLOCK",
        "KILL",
        "SHUTDOWN",
    }

    @classmethod
    def validate_sql(cls, sql: str) -> bool:
        """Validate SQL statement safety."""
        if not sql:
            return False

        # Remove SQL comments (-- and /* */) before validation.
        sql_clean = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean)
        sql_upper = sql_clean.strip().upper()

        # Check whether the statement starts with an allowed operation.
        if not any(sql_upper.startswith(op) for op in cls.ALLOWED_OPERATIONS):
            return False

        # Check dangerous keywords only at statement start to avoid false positives on column/table names.
        # Extract first word at the beginning of the statement.
        first_word_match = re.match(r"^\s*(\w+)", sql_upper)
        first_word = first_word_match.group(1) if first_word_match else ""

        # Check dangerous keywords only at the start.
        if first_word in cls.DANGEROUS_KEYWORDS:
            return False

        # Check SQL injection patterns.
        sql_injection_patterns = [
            r"\bor\s+1\s*=\s*1\b",
            r"\bunion\s+select\b",
            r"\bexec\s*\(",
            r"\bxp_cmdshell\b",
            r"\bsleep\s*\(",
            r"\bbenchmark\s*\(",
            r"\bwaitfor\s+delay\b",
            r"\b;\s*drop\b",
            r"\b;\s*delete\b",
            r"\b;\s*update\b",
            r"\b;\s*insert\b",
        ]

        for pattern in sql_injection_patterns:
            if re.search(pattern, sql_upper, re.IGNORECASE):
                return False

        return True

    @classmethod
    def validate_table_name(cls, table_name: str) -> bool:
        """Validate table name safety."""
        if not table_name:
            return False

        # Ensure table names contain only letters, numbers, and underscores.
        return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name))

    @classmethod
    def validate_timeout(cls, timeout: int) -> bool:
        """Validate timeout parameter."""
        return isinstance(timeout, int) and 1 <= timeout <= 600
