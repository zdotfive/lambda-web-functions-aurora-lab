from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct

from .network_stack import NetworkStack

AURORA_VERSION = "17.11"
DB_NAME = "lab"
PG_PORT = 5432


class DataStack(Stack):
    """Aurora PostgreSQL with a single db.t4g.medium writer, plus RDS Proxy."""

    def __init__(self, scope: Construct, construct_id: str, *, network: NetworkStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        isolated = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)

        self.sg_db = ec2.SecurityGroup(self, "sg-db", vpc=network.vpc, description="Aurora writer", security_group_name="lwf-sg-db")
        self.sg_proxy = ec2.SecurityGroup(self, "sg-proxy", vpc=network.vpc, description="RDS Proxy", security_group_name="lwf-sg-proxy")
        pg = ec2.Port.tcp(PG_PORT)
        self.sg_db.add_ingress_rule(network.sg_fn, pg, "functions direct")
        self.sg_db.add_ingress_rule(network.sg_loadgen, pg, "seed and pg_stat_activity sampler")
        self.sg_proxy.add_ingress_rule(network.sg_fn, pg, "functions via proxy")
        # The proxy reads the DB secret through the Secrets Manager endpoint.
        ec2.CfnSecurityGroupIngress(
            self,
            "EndpointFromProxy",
            group_id=network.sg_endpoint.security_group_id,
            source_security_group_id=self.sg_proxy.security_group_id,
            ip_protocol="tcp",
            from_port=443,
            to_port=443,
            description="Secrets Manager from RDS Proxy",
        )

        self.cluster = rds.DatabaseCluster(
            self,
            "Aurora",
            cluster_identifier="lwf-aurora",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.of(AURORA_VERSION, AURORA_VERSION.split(".")[0])
            ),
            writer=rds.ClusterInstance.provisioned(
                "writer",
                instance_identifier="lwf-aurora-writer",
                instance_type=ec2.InstanceType("t4g.medium"),
                publicly_accessible=False,
            ),
            credentials=rds.Credentials.from_generated_secret("labadmin", secret_name="lwf-aurora-admin"),
            default_database_name=DB_NAME,
            vpc=network.vpc,
            vpc_subnets=isolated,
            security_groups=[self.sg_db],
            storage_type=rds.DBClusterStorageType.AURORA,
            storage_encrypted=True,
            backup=rds.BackupProps(retention=Duration.days(1)),
            deletion_protection=False,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.secret = self.cluster.secret

        self.proxy = rds.DatabaseProxy(
            self,
            "Proxy",
            db_proxy_name="lwf-proxy",
            proxy_target=rds.ProxyTarget.from_cluster(self.cluster),
            secrets=[self.secret],
            vpc=network.vpc,
            vpc_subnets=isolated,
            security_groups=[self.sg_proxy],
            require_tls=True,
            iam_auth=False,
        )

        CfnOutput(self, "WriterEndpoint", value=self.cluster.cluster_endpoint.hostname)
        CfnOutput(self, "ProxyEndpoint", value=self.proxy.endpoint)
        CfnOutput(self, "DbSecretArn", value=self.secret.secret_arn)
        CfnOutput(self, "DbName", value=DB_NAME)
