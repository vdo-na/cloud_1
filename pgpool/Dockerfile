FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends pgpool2 postgresql-client \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /var/run/postgresql /tmp/pgpool \
 && chown -R postgres:postgres /var/run/postgresql /tmp/pgpool \
 && chmod 775 /var/run/postgresql

USER postgres

CMD ["pgpool", "-n", "-D", "-f", "/etc/pgpool2/pgpool.conf", "-F", "/etc/pgpool2/pcp.conf", "-a", "/etc/pgpool2/pool_hba.conf"]
