from aws_cdk import (
    aws_batch as batch,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_lambda as lmbda,
    aws_s3 as s3,
    core
)


class GplStack(core.Stack):

    def __init__(self, scope: core.Construct, id: str, props: dict, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Batch
        vpc = ec2.Vpc.from_lookup(
            self,
            'MainVPC',
            vpc_id='vpc-00eafc63c0dfca266',
        )

        batch_instance_role = iam.Role(
            self,
            'BatchInstanceRole',
            assumed_by=iam.ServicePrincipal('ec2.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonS3ReadOnlyAccess'),
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonSSMManagedInstanceCore'),
                iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AmazonEC2ContainerServiceforEC2Role'),
            ]
        )

        batch_instance_profile = iam.CfnInstanceProfile(
            self,
            'BatchInstanceProfile',
            roles=[batch_instance_role.role_name],
            instance_profile_name=f'{props["namespace"]}-batch-instance-profile',
        )

        batch_spot_fleet_role = iam.Role(
            self,
            'BatchSpotFleetRole',
            assumed_by=iam.ServicePrincipal('spotfleet.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AmazonEC2SpotFleetTaggingRole'),
            ]
        )

        batch_security_group = ec2.SecurityGroup.from_security_group_id(
            self,
            'SecruityGroupOutBoundOnly',
            'sg-0e4269cd9c7c1765a',
        )

        block_device_mappings = [
            ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                device_name='/dev/xvda',
                ebs=ec2.CfnLaunchTemplate.EbsProperty(
                    encrypted=True,
                    volume_size=500,
                    volume_type='gp2'
                )
            ),
        ]
        batch_launch_template = ec2.CfnLaunchTemplate(
            self,
            'BatchLaunchTemplate',
            launch_template_name=f'{props["namespace"]}-launch-template',
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                block_device_mappings=block_device_mappings,
            ),
        )
        batch_launch_template_spec = batch.LaunchTemplateSpecification(
            launch_template_name=batch_launch_template.launch_template_name,
            version='$Latest',
        )

        instance_types = [
            'm3.2xlarge',
            'm4.2xlarge',
            'm5.2xlarge',
            'm5a.2xlarge',
            'm5ad.2xlarge',
            'm5d.2xlarge',
            'm5zn.2xlarge',
            'r3.2xlarge',
            'r4.2xlarge',
        ]

        batch_compute_environment = batch.ComputeEnvironment(
            self,
            'BatchComputeEnvironment',
            compute_environment_name=f'{props["namespace"]}-compute-environment',
            compute_resources=batch.ComputeResources(
                vpc=vpc,
                allocation_strategy=batch.AllocationStrategy.SPOT_CAPACITY_OPTIMIZED,
                desiredv_cpus=0,
                instance_role=batch_instance_profile.attr_arn,
                instance_types=[ec2.InstanceType(it) for it in instance_types],
                launch_template=batch_launch_template_spec,
                maxv_cpus=64,
                security_groups=[batch_security_group],
                spot_fleet_role=batch_spot_fleet_role,
                type=batch.ComputeResourceType.SPOT,
            )
        )

        batch_job_queue = batch.JobQueue(
            self,
            'BatchJobQueue',
            job_queue_name=props['batch_queue_name'],
            compute_environments=[
                batch.JobQueueComputeEnvironment(
                    compute_environment=batch_compute_environment,
                    order=1
                )
            ]
        )

        # NOTE(SW): we specify container overrides for job definition when submitting each Batch job
        batch_job_definition = batch.JobDefinition(
            self,
            'BatchJobDefinition',
            job_definition_name=props['job_definition_name'],
            container=batch.JobDefinitionContainer(
                image=ecs.ContainerImage.from_registry(name=props['container_image']),
                command=['true'],
                memory_limit_mib=1000,
                vcpus=1,
            ),
        )

        # Lambda function: submit job
        # NOTE(SW): grant ro on specific buckets + prefixes
        submit_job_lambda_role = iam.Role(
            self,
            'SubmitJobLambdaRole',
            assumed_by=iam.ServicePrincipal('lambda.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AWSLambdaBasicExecutionRole'),
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonSSMReadOnlyAccess'),
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonS3ReadOnlyAccess'),
            ]
        )

        submit_job_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    'batch:SubmitJob'
                ],
                resources=[
                    batch_job_queue.job_queue_arn,
                    batch_job_definition.job_definition_arn,
                ]
            )
        )

        submit_job_lambda = lmbda.Function(
            self,
            'SubmitJobLambda',
            function_name=f'{props["namespace"]}_job_submitter',
            handler='lambda_entrypoint.main',
            runtime=lmbda.Runtime.PYTHON_3_8,
            code=lmbda.Code.from_asset('lambdas/submit_job/'),
            environment={
                'REFERENCE_DATA': props['reference_data'],
                'BATCH_QUEUE_NAME': props['batch_queue_name'],
                'JOB_DEFINITION_ARN': batch_job_definition.job_definition_arn,
                #'SLACK_NOTIFY': props['slack_notify'],
                #'SLACK_HOST': props['slack_host'],
                #'SLACK_CHANNEL': props['slack_channel'],
            },
            role=submit_job_lambda_role,
        )

        # S3 output directory
        roles_s3_write_access = [
            batch_instance_role,
            submit_job_lambda_role,
        ]
        umccr_temp_dev_bucket = s3.Bucket.from_bucket_name(
            self,
            'UmccrTempDevBucket',
            bucket_name=props['output_bucket'],
        )
        for role in roles_s3_write_access:
            umccr_temp_dev_bucket.grant_read_write(
                role,
                objects_key_pattern=props['output_prefix'],
            )
