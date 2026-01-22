#!/bin/sh
# Custom entrypoint to read postgres password from secret file

# Export postgres password for datasource provisioning
if [ -f /run/secrets/postgres_password ]; then
    export POSTGRES_PASSWORD=$(cat /run/secrets/postgres_password)
fi

# Run Grafana with all arguments
exec /run.sh "$@"
