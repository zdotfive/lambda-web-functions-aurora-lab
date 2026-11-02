from pathlib import Path

from aws_cdk import CfnOutput, Duration, Fn, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from .data_stack import DB_NAME, DataStack
from .network_stack import NetworkStack

APP_ZIP = Path(__file__).resolve().parents[2] / "build" / "app.zip"
WEB_FUNCTION = "lwf-web-pool"


class AppStack(Stack):
    """event-direct and event-proxy (Event Functions + Function URL) and web-pool (Web Function).

    Context (cdk deploy -c key=value):
      reserved_concurrency  per Event Function, unset by default (account limit is 10 until raised)
      pool_max              pg.Pool size in web-pool (default 10)
      max_environments      Web Function endpoint cap (default 20)
    """

    def __init__(self, scope: Construct, construct_id: str, *, network: NetworkStack, data: DataStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        reserved = self.node.try_get_context("reserved_concurrency")
        pool_max = str(self.node.try_get_context("pool_max") or 10)
        max_environments = int(self.node.try_get_context("max_environments") or 20)

        token = secretsmanager.Secret(
            self,
            "LabToken",
            secret_name="lwf-lab-token",
            generate_secret_string=secretsmanager.SecretStringGenerator(exclude_punctuation=True, password_length=32),
            removal_policy=RemovalPolicy.DESTROY,
        )

        def env_for(variant: str, host: str) -> dict:
            return {
                "VARIANT": variant,
                "DB_HOST": host,
                "DB_NAME": DB_NAME,
                "DB_SECRET_ARN": data.secret.secret_arn,
                # Resolved by CloudFormation at deploy time; the value is not in the template.
                "LAB_TOKEN": token.secret_value.unsafe_unwrap(),
            }

        code = lambda_.Code.from_asset(str(APP_ZIP))
        urls = {}

        # --- Event Functions: same code, the only difference is DB_HOST ---
        for variant, host in (
            ("event-direct", data.cluster.cluster_endpoint.hostname),
            ("event-proxy", data.proxy.endpoint),
        ):
            name = f"lwf-{variant}"
            log_group = logs.LogGroup(
                self,
                f"{variant}-logs",
                log_group_name=f"/aws/lambda/{name}",
                retention=logs.RetentionDays.ONE_DAY,
                removal_policy=RemovalPolicy.DESTROY,
            )
            fn = lambda_.Function(
                self,
                variant,
                function_name=name,
                runtime=lambda_.Runtime.NODEJS_24_X,
                architecture=lambda_.Architecture.ARM_64,
                memory_size=1024,
                timeout=Duration.seconds(30),
                handler="event/index.handler",
                code=code,
                environment=env_for(variant, host),
                vpc=network.vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
                security_groups=[network.sg_fn],
                reserved_concurrent_executions=int(reserved) if reserved else None,
                log_group=log_group,
            )
            data.secret.grant_read(fn)
            urls[variant] = fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE).url

        # --- Web Function ---
        # Web Functions read code only from a versioned bucket owned by the account (not the CDK bootstrap bucket).
        bucket = s3.Bucket(
            self,
            "CodeBucket",
            bucket_name=f"lwf-web-code-{self.account}",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal("lambda.amazonaws.com")],
                actions=["s3:GetObject", "s3:GetObjectVersion"],
                resources=[bucket.arn_for_objects("web/*")],
                conditions={
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:lambda:{self.region}:{self.account}:web-function/{WEB_FUNCTION}/revision/*"
                    }
                },
            )
        )

        # The zip lands under its asset hash, so a new build never overwrites an object a revision points to.
        # prune=False because deleting the object behind a revision breaks it for good.
        upload = s3deploy.BucketDeployment(
            self,
            "UploadWebZip",
            destination_bucket=bucket,
            sources=[s3deploy.Source.asset(str(APP_ZIP))],
            destination_key_prefix="web/",
            extract=False,
            prune=False,
        )
        uploaded_key = Fn.join("", ["web/", Fn.select(0, upload.object_keys)])

        web_logs = [
            logs.LogGroup(
                self,
                f"web-logs{suffix}",
                log_group_name=f"/aws/lambda/web/{WEB_FUNCTION}{suffix}",
                retention=logs.RetentionDays.ONE_DAY,
                removal_policy=RemovalPolicy.DESTROY,
            )
            for suffix in ("", ".local")
        ]

        execution_role = iam.Role(
            self,
            "WebExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        data.secret.grant_read(execution_role)
        for lg in web_logs:
            lg.grant_write(execution_role)

        operator_role = iam.Role(
            self,
            "ConnectorOperatorRole",
            # No aws:SourceAccount condition: with it the connector cannot assume the role.
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        # Docs, CLI help and the CloudFormation schema each list different permissions: grant the union.
        operator_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface"],
                resources=[
                    f"arn:aws:ec2:{self.region}:{self.account}:network-interface/*",
                    f"arn:aws:ec2:{self.region}:{self.account}:subnet/*",
                    f"arn:aws:ec2:{self.region}:{self.account}:security-group/*",
                ],
            )
        )
        operator_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ec2:CreateTags"],
                resources=[f"arn:aws:ec2:{self.region}:{self.account}:network-interface/*"],
                conditions={"StringEquals": {"ec2:ManagedResourceOperator": "network-connectors.lambda.amazonaws.com"}},
            )
        )
        operator_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ec2:DescribeNetworkInterfaces",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeVpcs",
                ],
                resources=["*"],
            )
        )

        connector = lambda_.CfnNetworkConnector(
            self,
            "NetworkConnector",
            name=f"{WEB_FUNCTION}-egress",
            operator_role=operator_role.role_arn,
            configuration=lambda_.CfnNetworkConnector.ConfigProperty(
                vpc_egress_configuration=lambda_.CfnNetworkConnector.VpcEgressConfigurationProperty(
                    subnet_ids=network.vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED).subnet_ids,
                    security_group_ids=[network.sg_fn.security_group_id],
                    network_protocol="IPv4",
                    associated_compute_resource_types=["WebFunction"],
                )
            ),
        )
        connector.node.add_dependency(operator_role)

        web_function = lambda_.CfnWebFunction(self, "WebFunction", function_name=WEB_FUNCTION)

        revision = lambda_.CfnWebFunctionRevision(
            self,
            "WebRevision",
            function_name=web_function.function_name,
            description=f"pool_max={pool_max}",
            build_config=lambda_.CfnWebFunctionRevision.BuildConfigProperty(
                runtime_config=lambda_.CfnWebFunctionRevision.RuntimeConfigProperty(runtime="nodejs24.x"),
                code_config=lambda_.CfnWebFunctionRevision.CodeConfigProperty(
                    s3_object=lambda_.CfnWebFunctionRevision.S3ObjectProperty(bucket=bucket.bucket_name, key=uploaded_key)
                ),
            ),
            service_config=lambda_.CfnWebFunctionRevision.ServiceConfigProperty(
                execution_role_arn=execution_role.role_arn,
                timeout_seconds=30,
                egress_network_connector_arn=connector.attr_latest_version_arn,
                environment_variables={
                    **env_for("web-pool", data.cluster.cluster_endpoint.hostname),
                    "POOL_MAX": pool_max,
                    # The runtime loads index.js from the zip root unless told otherwise.
                    "AWS_LAMBDA_NODEJS_ENTRYPOINT": "web/server.mjs",
                },
                telemetry_config=lambda_.CfnWebFunctionRevision.TelemetryConfigProperty(
                    logging_config=lambda_.CfnWebFunctionRevision.LoggingConfigProperty(
                        log_group=web_logs[0].log_group_name
                    )
                ),
            ),
        )
        revision.node.add_dependency(web_function)
        revision.node.add_dependency(upload, execution_role, *web_logs)

        endpoint = lambda_.CfnWebFunctionEndpoint(
            self,
            "WebEndpoint",
            function_name=web_function.function_name,
            endpoint_name="main",
            endpoint_type="HomeRegion",
            auth_type="ApplicationManaged",
            # CloudFormation has no AutoDeploymentMode: route 100% to the revision explicitly.
            revision_weights=[
                lambda_.CfnWebFunctionEndpoint.RevisionWeightProperty(revision_id=revision.attr_revision_id, weight=100)
            ],
            scaling_config=lambda_.CfnWebFunctionEndpoint.ScalingConfigProperty(max_environments=max_environments),
        )
        endpoint.node.add_dependency(revision)
        urls["web-pool"] = f"https://{endpoint.attr_domain_name}/"

        CfnOutput(self, "UrlEventDirect", value=urls["event-direct"])
        CfnOutput(self, "UrlEventProxy", value=urls["event-proxy"])
        CfnOutput(self, "UrlWebPool", value=urls["web-pool"])
        CfnOutput(self, "CodeBucketName", value=bucket.bucket_name)
        CfnOutput(self, "WebRevisionId", value=revision.attr_revision_id)
