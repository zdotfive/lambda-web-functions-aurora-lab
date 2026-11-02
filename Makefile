# Laptop: venv, app, synth, deploy, shell, pull-results, metrics, destroy, leftovers
# Loadgen (inside `make shell`, from a clone of this repo): env, seed, smoke, matrix, load, push-results
SHELL := /bin/bash
export AWS_REGION ?= eu-west-1
PY := .venv/bin/python
CDK := cd infra && npx --yes aws-cdk@2.1147.0
BUCKET = $$(aws cloudformation describe-stacks --stack-name LwfApp \
  --query "Stacks[0].Outputs[?OutputKey=='CodeBucketName'].OutputValue" --output text)
RDS_CA_URL := https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem

.PHONY: venv app synth deploy shell env seed smoke matrix load push-results pull-results metrics destroy leftovers

venv:
	uv venv -q .venv --python 3.13
	uv pip install -q --python $(PY) -r infra/requirements.txt

# One zip for all three variants: shared/, event/, web/, certs/ and node_modules/.
app:
	mkdir -p app/certs build
	curl -sSf -o app/certs/rds-global-bundle.pem $(RDS_CA_URL)
	cd app && npm install --omit=dev --no-audit --no-fund
	rm -f build/app.zip && cd app && zip -qr ../build/app.zip package.json shared event web certs node_modules

synth: app
	$(CDK) synth --quiet

deploy: app
	$(CDK) deploy --all --require-approval never

shell:
	aws ssm start-session --target $$(aws cloudformation describe-stacks --stack-name LwfNetwork \
	  --query "Stacks[0].Outputs[?OutputKey=='LoadgenInstanceId'].OutputValue" --output text)

env:
	scripts/loadgen_env.sh

seed:
	source .env && psql "$$DB_URL" -v ON_ERROR_STOP=1 -f scripts/seed.sql | tee results/raw/seed.log

smoke:
	scripts/smoke.sh

matrix:
	load/matrix.sh

load:
	load/matrix.sh --run

push-results:
	aws s3 sync results/raw s3://$(BUCKET)/results/raw

pull-results:
	aws s3 sync s3://$(BUCKET)/results/raw results/raw

metrics:
	$(PY) scripts/pull_metrics.py results/raw

destroy:
	$(CDK) destroy LwfApp --force
	$(CDK) destroy LwfData --force
	$(CDK) destroy LwfNetwork --force

leftovers:
	scripts/leftovers.sh
