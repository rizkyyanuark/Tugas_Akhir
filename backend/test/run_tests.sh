#!/bin/bash

set -euo pipefail

echo "Yuxi Test Runner"
echo "========================"

PYTEST_CMD=("docker" "compose" "exec" "api" "uv" "run" "--group" "test" "pytest")

check_server() {
    echo "Checking test server status..."
    if curl -s http://localhost:5050/api/system/health > /dev/null 2>&1; then
        echo "[OK] Test server is running"
        return 0
    fi

    echo "[WARN] Test server is not running or unreachable"
    echo "  Run docker compose up -d first and confirm api-dev is healthy"
    return 1
}

run_unit_tests() {
    echo "Running unit tests..."
    "${PYTEST_CMD[@]}" test/unit -m "not slow"
}

run_integration_tests() {
    echo "Running integration tests..."
    check_server
    "${PYTEST_CMD[@]}" test/integration
}

run_e2e_tests() {
    echo "Running end-to-end tests..."
    check_server
    "${PYTEST_CMD[@]}" test/e2e -m e2e
}

run_all_tests() {
    echo "Running all tests..."
    check_server
    "${PYTEST_CMD[@]}" test
}

show_help() {
    echo "Usage: $0 [option]"
    echo ""
    echo "Options:"
    echo "  unit         - Run unit tests"
    echo "  integration  - Run integration tests"
    echo "  e2e          - Run end-to-end tests"
    echo "  all          - Run all tests"
    echo "  check        - Check test services"
    echo "  help         - Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 unit"
    echo "  $0 integration"
    echo "  $0 e2e"
    echo "  $0 all"
}

case "${1:-all}" in
    "unit")
        run_unit_tests
        ;;
    "integration")
        run_integration_tests
        ;;
    "e2e")
        run_e2e_tests
        ;;
    "all")
        run_all_tests
        ;;
    "check")
        check_server
        ;;
    "help"|"-h"|"--help")
        show_help
        ;;
    *)
        echo "Unknown option: $1"
        show_help
        exit 1
        ;;
esac
