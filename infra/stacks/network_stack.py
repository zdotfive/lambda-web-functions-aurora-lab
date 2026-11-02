from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from constructs import Construct

LOADGEN_USER_DATA = """#!/bin/bash
set -eux
# Safety net: the instance terminates itself after 4 hours.
shutdown -h +240
dnf install -y postgresql17 jq git python3-boto3 https://dl.k6.io/rpm/repo.rpm
dnf install -y k6
"""


class NetworkStack(Stack):
    """VPC without NAT, security groups, Secrets Manager endpoint and the k6 load generator."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            availability_zones=["eu-west-1a", "eu-west-1b"],
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(name="isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24),
            ],
        )

        def sg(name: str, description: str) -> ec2.SecurityGroup:
            return ec2.SecurityGroup(
                self, name, vpc=self.vpc, description=description, security_group_name=f"lwf-{name}"
            )

        # sg-db and sg-proxy live in DataStack: RDS Proxy adds rules that reference the cluster port.
        self.sg_fn = sg("sg-fn", "Lambda Event Functions and Web Function network connector")
        self.sg_loadgen = sg("sg-loadgen", "k6 load generator")
        self.sg_endpoint = sg("sg-endpoint", "Secrets Manager interface endpoint")
        self.sg_endpoint.add_ingress_rule(self.sg_fn, ec2.Port.tcp(443), "Secrets Manager")

        self.vpc.add_interface_endpoint(
            "SecretsManager",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[self.sg_endpoint],
            private_dns_enabled=True,
        )

        loadgen_role = iam.Role(
            self,
            "LoadgenRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")],
        )
        # Read stack outputs and the lab secrets to build .env on the box (scripts/loadgen_env.sh).
        loadgen_role.add_to_policy(
            iam.PolicyStatement(actions=["cloudformation:DescribeStacks"], resources=["*"])
        )
        loadgen_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:lwf-*"],
            )
        )
        # The loadgen copies results/raw to the lab bucket (created in AppStack, named here to avoid a cycle).
        lab_bucket = f"arn:aws:s3:::lwf-web-code-{self.account}"
        loadgen_role.add_to_policy(
            iam.PolicyStatement(actions=["s3:ListBucket"], resources=[lab_bucket])
        )
        loadgen_role.add_to_policy(
            iam.PolicyStatement(actions=["s3:GetObject", "s3:PutObject"], resources=[f"{lab_bucket}/results/*"])
        )
        self.loadgen_role = loadgen_role

        user_data = ec2.UserData.custom(LOADGEN_USER_DATA)
        self.loadgen = ec2.Instance(
            self,
            "Loadgen",
            instance_name="lwf-loadgen",
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType("c7g.large"),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(cpu_type=ec2.AmazonLinuxCpuType.ARM_64),
            security_group=self.sg_loadgen,
            role=loadgen_role,
            user_data=user_data,
            associate_public_ip_address=True,
            instance_initiated_shutdown_behavior=ec2.InstanceInitiatedShutdownBehavior.TERMINATE,
            require_imdsv2=True,
            block_devices=[
                ec2.BlockDevice(device_name="/dev/xvda", volume=ec2.BlockDeviceVolume.ebs(20, delete_on_termination=True))
            ],
        )

        CfnOutput(self, "LoadgenInstanceId", value=self.loadgen.instance_id)
        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
