#!/usr/bin/env python3
import os


import aws_cdk


from deployment import GplStack


# Set config
tags = {
    'Creator': 'cdk',
    'Owner': 'swatts',
}

stack_props = {
    'stack_name': 'gridss-purple-linx',
    'namespace': 'gpl',
    'batch_queue_name': 'gpl-job-queue',
    'job_definition_name': 'gpl',
    'batch_resource_tags': tags,
}

aws_env = aws_cdk.Environment(
    account=os.environ['CDK_DEFAULT_ACCOUNT'],
    region=os.environ['CDK_DEFAULT_REGION'],
)

# Configure for deploy context
app = aws_cdk.App()
if (deploy_context_key := app.node.try_get_context('environment')) == None:
    raise ValueError('require deployment context as \'-c environment=<key>\' where <key> is define in cdk.json')
if (deploy_context := app.node.try_get_context(deploy_context_key)) == None:
    raise ValueError(f'no deploy context available for {deploy_context_key}')
stack_props.update(deploy_context)

# Create stack
GplStack(
    app,
    stack_props['stack_name'],
    stack_props,
    env=aws_env,
)

# Set tags
for k, v in tags.items():
    aws_cdk.Tags.of(app).add(key=k, value=v)
aws_cdk.Tags.of(app).add(key='Name', value=stack_props['namespace'])
app.synth()
