#!/usr/bin/env python3
import os

import aws_cdk as cdk

from stacks.app_stack import AppStack
from stacks.data_stack import DataStack
from stacks.network_stack import NetworkStack

app = cdk.App()
env = cdk.Environment(account=os.environ["CDK_DEFAULT_ACCOUNT"], region="eu-west-1")

network = NetworkStack(app, "LwfNetwork", env=env)
data = DataStack(app, "LwfData", env=env, network=network)
AppStack(app, "LwfApp", env=env, network=network, data=data)

cdk.Tags.of(app).add("project", "lwf-lab")
app.synth()
