#!/usr/bin/env bash
# Run on the loadgen: seeds the DB in the background (needs only LwfData), log in results/raw/seed.log.
set -euo pipefail
cd "$(dirname "$0")/.."
export AWS_REGION=${AWS_REGION:-eu-west-1}

out() {
  aws cloudformation describe-stacks --stack-name LwfData \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
secret=$(aws secretsmanager get-secret-value --secret-id "$(out DbSecretArn)" --query SecretString --output text)
export PGUSER=$(jq -r .username <<< "$secret") PGPASSWORD=$(jq -r .password <<< "$secret")
export PGHOST=$(out WriterEndpoint) PGDATABASE=$(out DbName) PGSSLMODE=require PGAPPNAME=lab-seed

mkdir -p results/raw
nohup bash -c "date -u +%FT%TZ; time psql -v ON_ERROR_STOP=1 -f scripts/seed.sql; date -u +%FT%TZ" > results/raw/seed.log 2>&1 &
echo "seed started, pid $!"
