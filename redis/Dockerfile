FROM docker.io/library/redis:8-alpine

ENV TZ=America/Bogota

EXPOSE 6379

ENTRYPOINT ["sh", "-c", "exec docker-entrypoint.sh redis-server --requirepass \"$REDIS_PASSWORD\" --appendonly yes"]
