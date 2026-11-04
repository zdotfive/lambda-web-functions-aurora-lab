#!/usr/bin/env bash
# Prints CLEAN only if nothing from the lab is left in the region; otherwise lists what is left.
set -uo pipefail
export AWS_REGION=${AWS_REGION:-eu-west-1}
TAG_KEY=project
TAG_VALUE=lwf-lab
left=0

report() {
  local what=$1 items=$2
  if [[ -n "$items" && "$items" != "None" ]]; then
    echo "LEFT $what: $items"
    left=1
  fi
}

report "RDS clusters" "$(aws rds describe-db-clusters --query "DBClusters[?TagList[?Key=='$TAG_KEY' && Value=='$TAG_VALUE']].DBClusterIdentifier" --output text)"
report "RDS instances" "$(aws rds describe-db-instances --query "DBInstances[?TagList[?Key=='$TAG_KEY' && Value=='$TAG_VALUE']].DBInstanceIdentifier" --output text)"
report "RDS proxies" "$(aws rds describe-db-proxies --query "DBProxies[?starts_with(DBProxyName, 'lwf-')].DBProxyName" --output text)"
report "Web Functions" "$(aws lambda-web list-web-functions --query "functions[?starts_with(functionName, 'lwf-')].functionName" --output text 2>/dev/null)"
report "Network connectors" "$(aws lambda-core list-network-connectors --query "NetworkConnectors[?starts_with(Name, 'lwf-')].Name" --output text 2>/dev/null)"
report "Lambda functions" "$(aws lambda list-functions --query "Functions[?starts_with(FunctionName, 'lwf-')].FunctionName" --output text)"
report "EC2 instances" "$(aws ec2 describe-instances --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" "Name=instance-state-name,Values=pending,running,stopping,stopped" --query 'Reservations[].Instances[].InstanceId' --output text)"
report "VPC endpoints" "$(aws ec2 describe-vpc-endpoints --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" --query 'VpcEndpoints[].VpcEndpointId' --output text)"
report "ENIs" "$(aws ec2 describe-network-interfaces --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" --query 'NetworkInterfaces[].NetworkInterfaceId' --output text)"
report "VPCs" "$(aws ec2 describe-vpcs --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" --query 'Vpcs[].VpcId' --output text)"
report "Elastic IPs" "$(aws ec2 describe-addresses --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" --query 'Addresses[].PublicIp' --output text)"
report "S3 buckets" "$(aws s3api list-buckets --query "Buckets[?starts_with(Name, 'lwf-')].Name" --output text)"
# Case-insensitive: the CDK custom resources log to /aws/lambda/LwfApp-... and /aws/lambda/LwfNetwork-...
report "Log groups" "$(aws logs describe-log-groups --query 'logGroups[].logGroupName' --output text | tr '\t' '\n' | grep -i lwf | tr '\n' ' ')"
report "Secrets" "$(aws secretsmanager list-secrets --filters Key=tag-key,Values=$TAG_KEY Key=tag-value,Values=$TAG_VALUE --query 'SecretList[].Name' --output text)"
report "CloudFormation stacks" "$(aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE ROLLBACK_COMPLETE DELETE_FAILED UPDATE_ROLLBACK_COMPLETE --query "StackSummaries[?starts_with(StackName, 'Lwf')].StackName" --output text)"

[[ $left == 0 ]] && echo CLEAN
exit $left
