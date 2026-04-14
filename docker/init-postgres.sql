-- Auto-create the 'airflow' database if it doesn't exist.
-- This script runs once when the postgres data volume is first initialized.
SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec
