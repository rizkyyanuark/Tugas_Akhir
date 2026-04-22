"""
Database Migration System
"""

import os
import shutil
import sqlite3
from pathlib import Path

from yunesa.utils import logger
from yunesa.utils.datetime_utils import shanghai_now


class DatabaseMigrator:
    """Database Migrator"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        self.migration_version_key = "migration_version"

    def ensure_backup_dir(self):
        """Ensure backup directory exists"""
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def backup_database(self) -> str:
        """Backup database file"""
        if not os.path.exists(self.db_path):
            logger.info("Database file does not exist, no backup needed")
            return ""

        self.ensure_backup_dir()
        timestamp = shanghai_now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"server_backup_{timestamp}.db"
        backup_path = os.path.join(self.backup_dir, backup_filename)

        try:
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"Database backed up to: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Database backup failed: {e}")
            raise

    def get_current_version(self) -> int:
        """Get current database version"""
        if not os.path.exists(self.db_path):
            return 0

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Check if version table exists
            cursor.execute("""
                                   SELECT name FROM sqlite_master
                                   WHERE type='table' AND name='migration_versions'            """)

            if not cursor.fetchone():
                # Version table does not exist, check if it is an old version database
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='users'
                """)
                if cursor.fetchone():
                    # User table exists but version table does not, indicating an old version
                    return 0
                else:
                    # Brand new database
                    return 0

            # Get current version
            cursor.execute("SELECT version FROM migration_versions ORDER BY version DESC LIMIT 1")
            result = cursor.fetchone()
            return result[0] if result else 0

        except Exception as e:
            logger.error(f"Failed to get database version: {e}")
            return 0
        finally:
            if "conn" in locals():
                conn.close()

    def set_version(self, version: int):
        """Set database version"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create version table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS migration_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)

            # Insert version record
            cursor.execute(
                """
                INSERT INTO migration_versions (version, description)
                VALUES (?, ?)
            """,
                (version, f"Migration to version {version}"),
            )

            conn.commit()
            logger.info(f"Database version set to: {version}")

        except Exception as e:
            logger.error(f"Failed to set database version: {e}")
            raise
        finally:
            if "conn" in locals():
                conn.close()

    def execute_migration(self, version: int, description: str, sql_commands: list[str]):
        """Execute migration"""
        logger.info(f"Executing migration v{version}: {description}")

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Execute migration SQL commands
            for sql in sql_commands:
                if sql.strip():  # Skip empty commands
                    logger.info(f"Executing SQL: {sql}")
                    cursor.execute(sql)

            conn.commit()
            logger.info(f"Migration v{version} executed successfully")

        except Exception as e:
            logger.error(f"Migration v{version} execution failed: {e}")
            raise
        finally:
            if "conn" in locals():
                conn.close()

    def check_column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if column exists"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [column[1] for column in cursor.fetchall()]
            return column_name in columns

        except Exception:
            return False
        finally:
            if "conn" in locals():
                conn.close()

    def check_table_exists(self, table_name: str) -> bool:
        """Check if table exists"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=?
            """,
                (table_name,),
            )
            return cursor.fetchone() is not None

        except Exception:
            return False
        finally:
            if "conn" in locals():
                conn.close()

    def run_migrations(self):
        """Run all pending migrations"""
        current_version = self.get_current_version()
        latest_version = self.get_latest_migration_version()

        # If database already exists but has no version table, create version table and set to latest version
        if current_version == 0 and latest_version > 0 and os.path.exists(self.db_path):
            # Check if users table already has new fields; if so, it was created via SQLAlchemy
            required_columns = [
                "login_failed_count",
                "last_failed_login",
                "login_locked_until",
                "is_deleted",
                "deleted_at",
            ]
            if all(self.check_column_exists("users", column) for column in required_columns):
                # Fields already exist, set directly to latest version
                logger.info(f"Detected existing database already contains latest fields, setting version to v{latest_version}")
                self.set_version(latest_version)
                return

        if current_version >= latest_version:
            logger.info(f"Database is already at latest version v{current_version}")
            return

        logger.info(f"Starting database migration: v{current_version} -> v{latest_version}")

        # Backup database
        backup_path = self.backup_database()

        try:
            # Execute migrations
            migrations = self.get_migrations()
            has_executed_migrations = False

            for version, description, sql_commands in migrations:
                if version > current_version:
                    if sql_commands:  # Only execute migration if there are SQL commands
                        self.execute_migration(version, description, sql_commands)
                        has_executed_migrations = True
                    else:
                        logger.info(f"Migration v{version}: {description} - No execution needed, fields already exist")

                    # Set version regardless of whether there were SQL commands
                    self.set_version(version)

            if has_executed_migrations:
                logger.info("Database migration completed")
            else:
                logger.info("Database structure is already up to date, only updating version record")

        except Exception as e:
            logger.error(f"Database migration failed: {e}")
            if backup_path and os.path.exists(backup_path):
                logger.info(f"Attempting to restore from backup: {backup_path}")
                try:
                    shutil.copy2(backup_path, self.db_path)
                    logger.info("Database restored from backup")
                except Exception as restore_error:
                    logger.error(f"Database restoration failed: {restore_error}")
            raise

    def get_latest_migration_version(self) -> int:
        """Get latest migration version number"""
        migrations = self.get_migrations()
        return max((version for version, _, _ in migrations), default=0)

    def get_migrations(self) -> list[tuple[int, str, list[str]]]:
        """Get all migration definitions
        Return format: [(version, description, [sql_commands])]
        """
        migrations = []

        # Migration v1: Add login failure limit fields to users table
        # Use conditional checks to avoid duplicate field addition
        v1_commands = []

        # Check and add login_failed_count field
        if not self.check_column_exists("users", "login_failed_count"):
            v1_commands.append("ALTER TABLE users ADD COLUMN login_failed_count INTEGER NOT NULL DEFAULT 0")

        # Check and add last_failed_login field
        if not self.check_column_exists("users", "last_failed_login"):
            v1_commands.append("ALTER TABLE users ADD COLUMN last_failed_login DATETIME")

        # Check and add login_locked_until field
        if not self.check_column_exists("users", "login_locked_until"):
            v1_commands.append("ALTER TABLE users ADD COLUMN login_locked_until DATETIME")

        migrations.append((1, "Add login failure limit fields to user table", v1_commands))

        # Migration v2: Add soft delete fields to users table
        v2_commands: list[str] = []

        if not self.check_column_exists("users", "is_deleted"):
            v2_commands.append("ALTER TABLE users ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")

        if not self.check_column_exists("users", "deleted_at"):
            v2_commands.append("ALTER TABLE users ADD COLUMN deleted_at DATETIME")

        migrations.append((2, "Add soft delete fields to user table", v2_commands))

        # Migration v3: Add multimodal image support to messages table
        v3_commands: list[str] = []

        if not self.check_column_exists("messages", "image_content"):
            v3_commands.append("ALTER TABLE messages ADD COLUMN image_content TEXT")

        migrations.append((3, "Add multimodal image support field to message table", v3_commands))

        # Migration v4: Add department functionality
        v4_commands: list[str] = []

        # Check if departments table exists
        if not self.check_table_exists("departments"):
            v4_commands.append("""
                CREATE TABLE departments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(50) NOT NULL UNIQUE,
                    description VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            v4_commands.append("CREATE INDEX idx_departments_name ON departments(name)")

        # Check if users table has department_id field
        if not self.check_column_exists("users", "department_id"):
            v4_commands.append("ALTER TABLE users ADD COLUMN department_id INTEGER REFERENCES departments(id)")

        v4_commands.append("CREATE INDEX idx_users_department_id ON users(department_id)")

        migrations.append((4, "Add department functionality", v4_commands))

        # Migration v5: Complete knowledge base/evaluation related table fields (add new columns for historical databases)
        v5_commands: list[str] = []

        # knowledge_bases
        if self.check_table_exists("knowledge_bases"):
            kb_columns = {
                "embed_info": "JSON",
                "llm_info": "JSON",
                "query_params": "JSON",
                "additional_params": "JSON",
                "share_config": "JSON",
                "mindmap": "JSON",
                "sample_questions": "JSON",
                "updated_at": "DATETIME",
            }
            for col, col_type in kb_columns.items():
                if not self.check_column_exists("knowledge_bases", col):
                    v5_commands.append(f"ALTER TABLE knowledge_bases ADD COLUMN {col} {col_type}")

        # knowledge_files
        if self.check_table_exists("knowledge_files"):
            kf_columns = {
                "parent_id": "VARCHAR(64)",
                "original_filename": "VARCHAR(512)",
                "file_type": "VARCHAR(64)",
                "path": "VARCHAR(1024)",
                "minio_url": "VARCHAR(1024)",
                "markdown_file": "VARCHAR(1024)",
                "status": "VARCHAR(32) DEFAULT 'uploaded'",
                "content_hash": "VARCHAR(128)",
                "file_size": "BIGINT",
                "content_type": "VARCHAR(64)",
                "processing_params": "JSON",
                "is_folder": "INTEGER NOT NULL DEFAULT 0",
                "error_message": "TEXT",
                "created_by": "VARCHAR(64)",
                "updated_by": "VARCHAR(64)",
                "updated_at": "DATETIME",
            }
            for col, col_type in kf_columns.items():
                if not self.check_column_exists("knowledge_files", col):
                    v5_commands.append(f"ALTER TABLE knowledge_files ADD COLUMN {col} {col_type}")

        # evaluation_benchmarks
        if self.check_table_exists("evaluation_benchmarks"):
            eb_columns = {
                "data_file_path": "VARCHAR(1024)",
                "created_by": "VARCHAR(64)",
                "updated_at": "DATETIME",
            }
            for col, col_type in eb_columns.items():
                if not self.check_column_exists("evaluation_benchmarks", col):
                    v5_commands.append(f"ALTER TABLE evaluation_benchmarks ADD COLUMN {col} {col_type}")

        # evaluation_results
        if self.check_table_exists("evaluation_results"):
            er_columns = {
                "retrieval_config": "JSON",
                "metrics": "JSON",
                "overall_score": "FLOAT",
                "total_questions": "INTEGER NOT NULL DEFAULT 0",
                "completed_questions": "INTEGER NOT NULL DEFAULT 0",
                "started_at": "DATETIME",
                "completed_at": "DATETIME",
                "created_by": "VARCHAR(64)",
            }
            for col, col_type in er_columns.items():
                if not self.check_column_exists("evaluation_results", col):
                    v5_commands.append(f"ALTER TABLE evaluation_results ADD COLUMN {col} {col_type}")

        # evaluation_result_details
        if self.check_table_exists("evaluation_result_details"):
            erd_columns = {
                "gold_chunk_ids": "JSON",
                "gold_answer": "TEXT",
                "generated_answer": "TEXT",
                "retrieved_chunks": "JSON",
                "metrics": "JSON",
            }
            for col, col_type in erd_columns.items():
                if not self.check_column_exists("evaluation_result_details", col):
                    v5_commands.append(f"ALTER TABLE evaluation_result_details ADD COLUMN {col} {col_type}")

        migrations.append((5, "Complete knowledge base and evaluation related table fields", v5_commands))

        # Future migrations can be added here
        # migrations.append((
        #     2,
        #     "添加新功能相关表",
        #     [
        #         "CREATE TABLE new_feature (...)",
        #         "ALTER TABLE existing_table ADD COLUMN new_field ..."
        #     ]
        # ))

        return migrations


def validate_database_schema(db_path: str) -> tuple[bool, list[str]]:
    """验证数据库结构是否符合当前模型

    Returns:
        tuple: (是否符合, 缺失的字段列表)
    """
    if not os.path.exists(db_path):
        return False, ["Database file does not exist"]

    missing_fields = []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check required fields for users table
        required_fields = {
            "users": [
                "id",
                "username",
                "user_id",
                "phone_number",
                "avatar",
                "password_hash",
                "role",
                "created_at",
                "last_login",
                "login_failed_count",
                "last_failed_login",
                "login_locked_until",
                "is_deleted",
                "deleted_at",
            ],
            "operation_logs": ["id", "user_id", "operation", "details", "ip_address", "timestamp"],
            "messages": [
                "id",
                "conversation_id",
                "role",
                "content",
                "message_type",
                "created_at",
                "token_count",
                "extra_metadata",
                "image_content",
            ],
            "knowledge_bases": [
                "id",
                "db_id",
                "name",
                "kb_type",
                "query_params",
                "additional_params",
                "share_config",
                "mindmap",
                "sample_questions",
                "created_at",
                "updated_at",
            ],
            "knowledge_files": [
                "id",
                "file_id",
                "db_id",
                "filename",
                "file_type",
                "status",
                "is_folder",
                "created_at",
                "updated_at",
            ],
            "evaluation_benchmarks": [
                "id",
                "benchmark_id",
                "db_id",
                "name",
                "question_count",
                "has_gold_chunks",
                "has_gold_answers",
                "data_file_path",
                "created_at",
                "updated_at",
            ],
            "evaluation_results": [
                "id",
                "task_id",
                "db_id",
                "benchmark_id",
                "status",
                "retrieval_config",
                "metrics",
                "overall_score",
                "total_questions",
                "completed_questions",
                "started_at",
                "completed_at",
            ],
            "evaluation_result_details": [
                "id",
                "task_id",
                "query_index",
                "query_text",
                "gold_chunk_ids",
                "gold_answer",
                "generated_answer",
                "retrieved_chunks",
                "metrics",
            ],
        }

        for table_name, fields in required_fields.items():
            # Check if table exists
            cursor.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=?
            """,
                (table_name,),
            )

            if not cursor.fetchone():
                missing_fields.append(f"Table {table_name} does not exist")
                continue

            # Check if fields exist
            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_columns = [column[1] for column in cursor.fetchall()]

            for field in fields:
                if field not in existing_columns:
                    missing_fields.append(f"Table {table_name} is missing field {field}")

        return len(missing_fields) == 0, missing_fields

    except Exception as e:
        logger.error(f"Failed to validate database structure: {e}")
        return False, [f"Validation failed: {str(e)}"]
    finally:
        if "conn" in locals():
            conn.close()


def check_and_migrate(db_path: str):
    """Check and execute database migrations"""
    # Validate database structure first
    is_valid, issues = validate_database_schema(db_path)

    if not is_valid:
        logger.warning("Database structure does not comply with current design:")
        for issue in issues:
            logger.warning(f"  - {issue}")

        if os.path.exists(db_path):
            logger.info("Suggested running migration script: docker exec api-dev python /app/scripts/migrate_user_soft_delete.py")

    migrator = DatabaseMigrator(db_path)

    try:
        migrator.run_migrations()
        return True
    except Exception as e:
        logger.error(f"Error occurred during database migration: {e}")
        return False
