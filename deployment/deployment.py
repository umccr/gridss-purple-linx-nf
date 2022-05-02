# pylint: disable=missing-class-docstring


from aws_cdk import (
    aws_batch_alpha as batch,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_lambda as lmbda,
    aws_s3 as s3,
    Stack,
    Duration,
)


class GplStack(Stack):
    # pylint: disable=redefined-builtin

    def __init__(self, scope, id, props, **kwargs):
        super().__init__(scope, id, **kwargs)

        # Lambda Function URL CORS Setting
        fn_url_cors_options = lmbda.FunctionUrlCorsOptions(
            allowed_origins=[
                'https://data.umccr.org',
                'https://data.dev.umccr.org',
                'https://data.prod.umccr.org',
            ],
            allowed_methods=[lmbda.HttpMethod.GET, lmbda.HttpMethod.POST]
        )

        fn_url_auth_type = lmbda.FunctionUrlAuthType.AWS_IAM  # IAM is the only option for now

        # Batch
        vpc = ec2.Vpc.from_lookup(
            self,
            'VPC',
            vpc_name='main-vpc',
            tags={'Stack': 'networking'},
        )

        batch_instance_role = iam.Role(
            self,
            'BatchInstanceRole',
            assumed_by=iam.ServicePrincipal('ec2.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonS3ReadOnlyAccess'),
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonSSMManagedInstanceCore'),
                iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AmazonEC2ContainerServiceforEC2Role'),
            ],
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
            ],
        )

        batch_security_group = ec2.SecurityGroup.from_lookup_by_name(
            self,
            'SecruityGroupOutBoundOnly',
            'main-vpc-sg-outbound',
            vpc,
        )

        block_device_mappings = [
            ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                device_name='/dev/xvda',
                ebs=ec2.CfnLaunchTemplate.EbsProperty(encrypted=True, volume_size=500, volume_type='gp2'),
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
                maxv_cpus=128,
                security_groups=[batch_security_group],
                spot_fleet_role=batch_spot_fleet_role,
                type=batch.ComputeResourceType.SPOT,
                compute_resources_tags={
                    'Name': props['namespace'],
                    'Creator': props['batch_resource_tags']['Creator'],
                    'Owner': props['batch_resource_tags']['Owner'],
                },
            ),
        )

        batch_job_queue = batch.JobQueue(
            self,
            'BatchJobQueue',
            job_queue_name=props['batch_queue_name'],
            compute_environments=[
                batch.JobQueueComputeEnvironment(compute_environment=batch_compute_environment, order=1)
            ],
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

        # Lambda layers
        runtime_layer = lmbda.LayerVersion(
            self,
            'RuntimeLambdaLayer',
            code=lmbda.Code.from_asset('lambdas/layers/runtime/build/python38-runtime.zip'),
            compatible_runtimes=[lmbda.Runtime.PYTHON_3_8],
            description='A runtime layer for Python 3.8',
        )

        util_layer = lmbda.LayerVersion(
            self,
            'UtilLambdaLayer',
            code=lmbda.Code.from_asset('lambdas/layers/util/build/python38-util.zip'),
            compatible_runtimes=[lmbda.Runtime.PYTHON_3_8],
            description='A shared utility layer for Python 3.8',
        )

        # Lambda function: submit job (manual)
        submit_job_manual_lambda_role = iam.Role(
            self,
            'SubmitJobManualLambdaRole',
            assumed_by=iam.ServicePrincipal('lambda.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonS3ReadOnlyAccess'),
                iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AWSLambdaBasicExecutionRole'),
            ],
        )

        submit_job_manual_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    'batch:DeregisterJobDefinition',
                    'batch:RegisterJobDefinition',
                    'batch:SubmitJob',
                ],
                resources=[
                    batch_job_queue.job_queue_arn,
                    f'arn:aws:batch:{self.region}:{self.account}:job-definition/{props["job_definition_name"]}*',
                ],
            )
        )

        submit_job_manual_lambda_role.add_to_policy(
            iam.PolicyStatement(actions=['batch:DescribeJobDefinitions'], resources=['*'])
        )

        submit_job_manual_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=['ecr:ListImages'],
                # NOTE(SW): this should be defined elsewhere
                resources=['arn:aws:ecr:ap-southeast-2:843407916570:repository/gpl-nf'],
            )
        )

        submit_job_manual_lambda = lmbda.Function(
            self,
            'SubmitJobManualLambda',
            function_name=f'{props["namespace"]}_submit_job_manual',
            handler='lambda_entrypoint.main',
            runtime=lmbda.Runtime.PYTHON_3_8,
            code=lmbda.Code.from_asset('lambdas/submit_job_manual/'),
            environment={
                'REFERENCE_DATA': props['reference_data'],
                'BATCH_QUEUE_NAME': props['batch_queue_name'],
                'JOB_DEFINITION_ARN': batch_job_definition.job_definition_arn,
                'JOB_DEFINITION_NAME': props['job_definition_name'],
            },
            role=submit_job_manual_lambda_role,
            layers=[
                util_layer,
            ],
        )
        submit_job_manual_lambda_fn_url = submit_job_manual_lambda.add_function_url(
            auth_type=fn_url_auth_type,
            cors=fn_url_cors_options
        )
        core.CfnOutput(self, 'SubmitJobManualLambdaUrl', value=submit_job_manual_lambda_fn_url.url)

        # Lambda function: submit job (automated input collection)
        submit_job_lambda_role_policy = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    actions=['lambda:InvokeFunction'], resources=[submit_job_manual_lambda.function_arn]
                ),
                iam.PolicyStatement(actions=['execute-api:Invoke'], resources=['*']),
            ]
        )

        submit_job_lambda_role = iam.Role(
            self,
            'SubmitJobLambdaRole',
            assumed_by=iam.ServicePrincipal('lambda.amazonaws.com'),
            inline_policies=[submit_job_lambda_role_policy],
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AWSLambdaBasicExecutionRole'),
            ],
        )

        lmbda.Function(
            self,
            'SubmitJobLambda',
            function_name=f'{props["namespace"]}_submit_job',
            handler='lambda_entrypoint.main',
            runtime=lmbda.Runtime.PYTHON_3_8,
            code=lmbda.Code.from_asset('lambdas/submit_job/'),
            environment={
                'PORTAL_API_BASE_URL': props['portal_api_base_url'],
                'SUBMISSION_LAMBDA_ARN': submit_job_manual_lambda.function_arn,
                'OUTPUT_BUCKET': props['output_bucket'],
            },
            role=submit_job_lambda_role,
            timeout=Duration.seconds(60),
            layers=[
                runtime_layer,
                util_layer,
            ],
        )
        submit_job_lambda_fn_url = submit_job_lambda.add_function_url(
            auth_type=fn_url_auth_type,
            cors=fn_url_cors_options
        )
        core.CfnOutput(self, 'SubmitJobLambdaUrl', value=submit_job_lambda_fn_url.url)

        # Lambda function: create LINX plots
        create_linx_plot_lambda_role = iam.Role(
            self,
            'CreateLinxPlotLambdaRole',
            assumed_by=iam.ServicePrincipal('lambda.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonS3ReadOnlyAccess'),
                iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AWSLambdaBasicExecutionRole'),
            ],
        )

        create_linx_plot_docker_image = lmbda.Code.from_asset_image(
            directory='./',
            file='docker/Dockerfile.create_linx_plot_lambda',
        )

        lmbda.Function(
            self,
            'CreateLinxPlotLambda',
            function_name=f'{props["namespace"]}_create_linx_plot',
            code=create_linx_plot_docker_image,
            handler=lmbda.Handler.FROM_IMAGE,
            runtime=lmbda.Runtime.FROM_IMAGE,
            timeout=Duration.minutes(10),
            memory_size=5120,
            environment={
                'OUTPUT_BUCKET': props['output_bucket'],
                'REFERENCE_DATA': props['reference_data'],
            },
            role=create_linx_plot_lambda_role,
        )
        create_linx_plot_lambda_fn_url = create_linx_plot_lambda.add_function_url(
            auth_type=fn_url_auth_type,
            cors=fn_url_cors_options
        )
        core.CfnOutput(self, 'CreateLinxPlotLambdaUrl', value=create_linx_plot_lambda_fn_url.url)

        # S3 output directory
        roles_s3_write_access = [
            batch_instance_role,
            create_linx_plot_lambda_role,
        ]
        output_bucket = s3.Bucket.from_bucket_name(
            self,
            'OutputBucket',
            bucket_name=props['output_bucket'],
        )
        for role in roles_s3_write_access:
            output_bucket.grant_put(role, '*/gridss_purple_linx/*')
