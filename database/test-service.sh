#!/bin/sh
# Explicit opt-in smoke test. Never uses development credentials or deletes volumes.
set -eu

command -v docker >/dev/null 2>&1 || {
    printf '%s\n' 'Docker no está instalado; no se puede ejecutar el test del servicio.' >&2
    exit 1
}
docker compose version >/dev/null 2>&1 || {
    printf '%s\n' 'Se necesita Docker Compose v2.' >&2
    exit 1
}
docker info >/dev/null 2>&1 || {
    printf '%s\n' 'Docker no está disponible. Arranca Docker Desktop o el daemon configurado.' >&2
    exit 1
}

DATABASE_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(dirname "$DATABASE_DIR")
TEST_PROJECT="core-banking-db-test-$$"
WORK_DIR=$(mktemp -d)
TEST_ENV="$WORK_DIR/postgres.env"
PROBE_TABLE="infra_probe_$$"
TABLE_CREATED=0

# Prevent exported development variables from overriding the isolated test file.
unset POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB POSTGRES_PORT POSTGRES_VOLUME_NAME
cat > "$TEST_ENV" <<'ENV'
POSTGRES_USER=infra_test
POSTGRES_PASSWORD=infra_test_only
POSTGRES_DB=core_banking_test
POSTGRES_PORT=0
ENV
printf 'POSTGRES_VOLUME_NAME=%s_postgres_data\n' "$TEST_PROJECT" >> "$TEST_ENV"

compose() {
    docker compose --project-name "$TEST_PROJECT" --project-directory "$DATABASE_DIR" \
        --env-file "$TEST_ENV" -f "$DATABASE_DIR/compose.yml" "$@"
}

sql() {
    compose exec -T postgres sh -c \
        'exec psql -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"' "$@"
}

ready() {
    compose exec -T postgres sh -c \
        'exec pg_isready -h 127.0.0.1 -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}

cleanup() {
    result=$?
    trap - 0
    if [ "$TABLE_CREATED" -eq 1 ]; then
        if ! printf 'DROP TABLE IF EXISTS %s;\n' "$PROBE_TABLE" | sql; then
            printf '%s\n' 'No se pudo limpiar la tabla de prueba en el volumen aislado.' >&2
            result=1
        fi
    fi
    if ! compose down; then
        printf '%s\n' 'No se pudo detener el proyecto aislado de pruebas.' >&2
        result=1
    fi
    printf 'Volumen de pruebas conservado: %s_postgres_data\n' "$TEST_PROJECT"
    rm -f "$TEST_ENV"
    rmdir "$WORK_DIR"
    exit "$result"
}
trap cleanup 0
trap 'exit 1' 1 2 15

printf '%s\n' '[1/5] Validar Compose de PostgreSQL y la independencia de la API.'
compose config --quiet
[ "$(compose config --services)" = postgres ]
[ "$(docker compose -f "$ROOT_DIR/docker-compose.yml" config --services)" = api ]

printf '%s\n' '[2/5] Arrancar dos veces y esperar a PostgreSQL saludable.'
compose up -d --wait --wait-timeout 120 postgres
compose up -d --wait --wait-timeout 120 postgres
compose ps -a postgres
ready

printf '%s\n' '[3/5] Verificar usuario/base y crear un registro desechable.'
[ "$(printf 'SELECT current_database();\n' | sql)" = core_banking_test ]
[ "$(printf 'SELECT current_user;\n' | sql)" = infra_test ]
printf 'SELECT version();\n' | sql
TABLE_CREATED=1
printf 'CREATE TABLE %s (value integer NOT NULL); INSERT INTO %s VALUES (1);\n' \
    "$PROBE_TABLE" "$PROBE_TABLE" | sql

printf '%s\n' '[4/5] Detener, arrancar y comprobar persistencia.'
compose stop postgres
compose up -d --wait --wait-timeout 120 postgres
ready
[ "$(printf 'SELECT value FROM %s;\n' "$PROBE_TABLE" | sql)" = 1 ]

printf '%s\n' '[5/5] Eliminar solo la tabla desechable.'
printf 'DROP TABLE %s;\n' "$PROBE_TABLE" | sql
TABLE_CREATED=0
printf '%s\n' 'Comprobaciones del servicio PostgreSQL correctas.'
