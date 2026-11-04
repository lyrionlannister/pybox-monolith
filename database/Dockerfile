FROM docker.io/library/postgres:18-alpine

# POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD no se fijan aquí: son credenciales y
# las inyecta docker-compose.yaml desde el .env raíz.
ENV TZ=America/Bogota \
    POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
    POSTGRES_INITDB_ARGS="--auth-host=scram-sha-256 --auth-local=scram-sha-256"

EXPOSE 5432

CMD ["postgres", "-c", "timezone=America/Bogota"]
