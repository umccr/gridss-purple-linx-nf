#!/usr/bin/env python3
import os


from aws_cdk import core


from deployment import GplStack


# Set config
stack_props = {
    'namespace': 'gpl',
    'reference_data': 's3://umccr-refdata-dev/gpl-nf/',
    'batch_queue_name': 'gpl-job-queue',
    'job_definition_name': 'gpl',
    'container_image': '843407916570.dkr.ecr.ap-southeast-2.amazonaws.com/gpl-nf:0.0.3',
    'slack_notify': 'no',
    'slack_host': 'hooks.slack.com',
    'slack_channel': '#arteria-dev',
    'output_bucket': 'umccr-temp-dev',
    'output_prefix': 'stephen/gpl_output/*',
}
aws_env = {
    'account': os.environ.get('CDK_DEFAULT_ACCOUNT'),
    'region': os.environ.get('CDK_DEFAULT_REGION'),
}
# Create stack
app = core.App()
GplStack(
    app,
    stack_props['namespace'],
    stack_props,
    env=aws_env,
)
# Set tags
tags = {
    'Stack': stack_props['namespace'],
    'Creator': 'cdk',
    'Owner': 'swatts',
}
for k, v in tags.items():
    core.Tags.of(app).add(key=k, value=v)
app.synth()
