#!/usr/bin/env bash
# Run on the loadgen (via SSM) after `make deploy`: writes .env from the stack outputs and the secrets.
# Nothing is printed; .env stays on the instance and is git-ignored.
set -euo pipefail
cd "$(dirname "$0")/.."
export AWS_REGION=${AWS_REGION:-eu-west-1}

out() {
  aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}
secret_json() {
  aws secretsmanager get-secret-value --secret-id "$1" --query SecretString --output text
}

db_secret=$(secret_json "$(out LwfData DbSecretArn)")
user=$(jq -r .username <<< "$db_secret")
pass=$(jq -r '.password | @uri' <<< "$db_secret")

umask 077
cat > .env <<EOF
AWS_REGION=$AWS_REGION
DB_URL='postgresql://$user:$pass@$(out LwfData WriterEndpoint):5432/$(out LwfData DbName)?sslmode=require&application_name=lab-sampler'
LAB_TOKEN=$(secret_json lwf-lab-token)
URL_EVENT_DIRECT=$(out LwfApp UrlEventDirect)
URL_EVENT_PROXY=$(out LwfApp UrlEventProxy)
URL_WEB_POOL=$(out LwfApp UrlWebPool)
EOF
echo ".env written"
