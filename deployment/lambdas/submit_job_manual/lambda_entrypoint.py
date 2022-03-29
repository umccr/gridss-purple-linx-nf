#!/usr/bin/env python3
import json
import logging
import os
import re
import sys


import botocore


import util


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


#SLACK_NOTIFY = get_environment_variable('SLACK_NOTIFY')
#SLACK_HOST = get_environment_variable('SLACK_HOST')
#SLACK_CHANNEL = get_environment_variable('SLACK_CHANNEL')
REFERENCE_DATA = util.get_environment_variable('REFERENCE_DATA')
BATCH_QUEUE_NAME = util.get_environment_variable('BATCH_QUEUE_NAME')
JOB_DEFINITION_ARN = util.get_environment_variable('JOB_DEFINITION_ARN')
JOB_DEFINITION_NAME = util.get_environment_variable('JOB_DEFINITION_NAME')

CLIENT_BATCH = util.get_client('batch')
CLIENT_ERC = util.get_client('ecr')
CLIENT_S3 = util.get_client('s3')
RESOURCE_S3 = util.get_resource('s3')

FILE_EXTENSIONS = {
    'bam': {'bam'},
    'vcf': {'vcf', 'vcf.gz'},
}


# NOTE(SW): these should be provided from elsewhere
ERC_REPO_NAME = 'gpl-nf'
ERC_IMAGE_NAME = f'843407916570.dkr.ecr.ap-southeast-2.amazonaws.com/{ERC_REPO_NAME}'


def main(event, context):
    # Log invocation data
    LOGGER.info(f'event: {json.dumps(event)}')
    LOGGER.info(f'context: {json.dumps(util.get_context_info(context))}')

    # Check inputs and ensure that output directory is writable
    if response_error := validate_event_data(event):
        return response_error
    if response_error := check_s3_output_dir_writable(event['output_dir']):
        return response_error

    # Construct command
    tumor_smlv_vcf_fp_arg = get_argument_string('tumor_smlv_vcf_fp', 'tumor_smlv_vcf', event)
    tumor_sv_vcf_fp_arg = get_argument_string('tumor_sv_vcf_fp', 'tumor_sv_vcf', event)
    nf_args_str_arg = get_argument_string('nextflow_args_str', 'nextflow_args_str', event)
    upload_nf_cache_arg = '--upload_nf_cache' if 'upload_nf_cache' in event else ''
    command_indented = f'''
        /opt/gpl_pipeline/run_gpl.py
            --tumor_name {event["tumor_name"]}
            --normal_name {event["normal_name"]}
            --tumor_bam_fp {event["tumor_bam"]}
            --normal_bam_fp {event["normal_bam"]}
            {tumor_smlv_vcf_fp_arg}
            {tumor_sv_vcf_fp_arg}
            --reference_data {REFERENCE_DATA}
            --output_dir {event["output_dir"]}
            {upload_nf_cache_arg}
            --cpu_count {event["instance_vcpus"]}
            {nf_args_str_arg}
    '''
    command = re.sub(r'[ \n]+', ' ', command_indented).strip()
    command_full = ['bash', '-o', 'pipefail', '-c', command]

    # If provided a Docker image that does not have a corresponding job definition, create it and
    # use below
    if docker_image_tag := event.get('docker_image_tag'):
        job_definition_arn = get_job_definition_arn(docker_image_tag)
    else:
        job_definition_arn = JOB_DEFINITION_ARN

    # Submit job
    if not (job_name := event.get('job_name')):
        job_name = f'gpl__{event["tumor_name"]}__{event["normal_name"]}'
    instance_memory = int(event['instance_memory']) * 1000
    instance_vcpus = int(event['instance_vcpus'])
    response_job = CLIENT_BATCH.submit_job(
        jobName=job_name,
        jobQueue=BATCH_QUEUE_NAME,
        jobDefinition=job_definition_arn,
        containerOverrides={
            'memory': instance_memory,
            'vcpus': instance_vcpus,
            'command': command_full,
        }
    )
    if not (job_id := response_job.get('jobId')):
        msg = f'could not get jobId from Batch job submission response: {response_job}'
        return log_error_and_get_response(msg, level='critical')
    # Deregister job definition if created by Lambda
    if job_definition_arn != JOB_DEFINITION_ARN:
        CLIENT_BATCH.deregister_job_definition(jobDefinition=job_definition_arn)
    return {
        'statusCode': 200,
        'body': f'submitted job id: {job_id}'
    }


def validate_event_data(event):
    arguments = {
        'job_name':                 {'required': False},
        'tumor_name':               {'required': True},
        'normal_name':              {'required': True},
        'tumor_bam':                {'required': True,  's3_input': True, 'filetype': 'bam'},
        'normal_bam':               {'required': True,  's3_input': True, 'filetype': 'bam'},
        'tumor_smlv_vcf':           {'required': False, 's3_input': True, 'filetype': 'vcf'},
        'tumor_sv_vcf':             {'required': False, 's3_input': True, 'filetype': 'vcf'},
        'output_dir':               {'required': True},
        'upload_nf_cache':          {'required': False},
        'docker_image_tag':         {'required': False},
        'nextflow_args_str':        {'required': False},
        'instance_memory':          {'required': False, 'type_int': True, 'default': 30},
        'instance_vcpus':           {'required': False, 'type_int': True, 'default': 8},
    }

    # NOTE(SW): requiring that all jobs have exactly 8 vCPUs to optimise instance provisioning and
    # to avoid exceed storage limits.
    if 'instance_vcpus' in event and event['instance_vcpus'] != 8:
        msg = f'currently only accepting jobs with exactly 8 vCPUs, got: {event["instance_vcpus"]}'
        return log_error_and_get_response(msg)

    # Set defaults if values not provided
    for arg in arguments:
        if arg in event:
            continue
        if not (arg_default := arguments[arg].get('default')):
            continue
        event[arg] = arg_default

    # Require job name to conform to Batch requirements
    if job_name := event.get('job_name'):
        batch_job_name_re = re.compile(r'^[0-9a-zA-Z][\w_-]*$')
        if not batch_job_name_re.match(job_name):
            msg_1 = f'invalid \'job_name\' ({job_name}) - must start with an alphanumeric, and can'
            msg_2 = 'contain letters (upper and lower case), numbers, hypens, and underscores'
            return log_error_and_get_response(f'{msg_1} {msg_2}')
        if len(job_name) > 128:
            msg = f'\'job_name\' is {len(job_name)} characters long but must be no longer than 128 characters'
            return log_error_and_get_response(msg)

    # Get Nextflow arguments string, ensure quoted
    if nextflow_arg_str := event.get('nextflow_args_str'):
        quotes_valid = set('\'"')
        if nextflow_arg_str[0] not in quotes_valid or nextflow_arg_str[-1] not in quotes_valid:
            # NOTE(SW): doesn't guarantee quotes are matching
            msg = f'provided Nextflow arguments must be wrapped in quotes, got:\n\t{nextflow_arg_str}'
            return log_error_and_get_response(msg)

    # Check for unknown/extra arguments
    args_unknown = [arg for arg in event if arg not in arguments]
    if args_unknown:
        plurality = 'arguments' if len(args_unknown) > 1 else 'argument'
        args_unknown_str = '\n\t'.join(args_unknown)
        msg = f'got {len(args_unknown)} unknown arguments:\n\t{args_unknown_str}'
        return log_error_and_get_response(msg)

    # Check for required arguments
    args_missing = list()
    for arg_required in (arg for arg in arguments if arguments[arg].get('required')):
        if arg_required in event:
            continue
        args_missing.append(arg_required)
    if args_missing:
        plurality = 'arguments' if len(args_missing) > 1 else 'argument'
        args_missing_str = '\n\t'.join(args_missing)
        msg = f'missing {len(args_missing)} arguments:\n\t{args_missing_str}'
        return log_error_and_get_response(msg)

    # Check input files
    s3_inputs = list()
    file_input_errors = {'bad_form': list(), 'bad_extension': list()}
    for arg_s3_input in (arg for arg in arguments if arguments[arg].get('s3_input')):
        if arg_s3_input not in event:
            continue
        # S3 path
        s3_path = event[arg_s3_input]
        if not (re_result := match_s3_path(s3_path)):
            file_input_errors['bad_form'].append((arg_s3_input, s3_path))
            continue
        # Filetype, extension
        filename = re_result['key_name']
        filetype = arguments[arg_s3_input]['filetype']
        if not any(filename.endswith(fext) for fext in FILE_EXTENSIONS[filetype]):
            file_input_errors['bad_extension'].append((arg_s3_input, s3_path))
            continue
        # Record for later use
        s3_inputs.append((arg_s3_input, s3_path))
    # Report errors
    msgs = list()
    for error_type, file_list in file_input_errors.items():
        if not file_list:
            continue
        files_strs = [f'{arg}: {value}' for arg, value in file_list]
        files_str = '\n\t'.join(files_strs)
        plurality = 'files' if len(file_list) > 1 else 'file'
        if error_type == 'bad_form':
            msg = f'got malformed S3 path for {len(file_list)} {plurality}:\n\t{files_str}'
        elif error_type == 'bad_extension':
            msg = f'got bad file extension for {len(file_list)} {plurality}:\n\t{files_str}'
        else:
            assert False
        msgs.append(msg)
    if msgs:
        return log_error_and_get_response('\n'.join(msgs))

    # Locate input files
    file_locate_errors = list()
    for (arg_s3_input, s3_path) in s3_inputs:
        # Run S3.Client.head_object via S3.Object.load
        # From previous checks, can assume value is in 'event' and regex will be successful
        s3_path_components = match_s3_path(s3_path)
        check_s3_file_exists(
            s3_path_components['bucket_name'],
            s3_path_components['key'],
            file_locate_errors,
        )
        # Ensure BAMs are co-located with indexes
        filetype = arguments[arg_s3_input]['filetype']
        if filetype == 'bam':
            s3_path_index = f'{s3_path_components["key"]}.bai'
            check_s3_file_exists(
                s3_path_components['bucket_name'],
                s3_path_index,
                file_locate_errors,
            )
    # Report errors
    if file_locate_errors:
        plurality = 'files' if len(file_locate_errors) > 1 else 'file'
        files_strs = list()
        for code, message, s3_path in file_locate_errors:
            files_strs.append(f'{s3_path}: {message} ({code})')
        files_str = '\n\t'.join(files_strs)
        msg = f'failed to locate {len(file_locate_errors)} {plurality}:\n\t{files_str}'
        return log_error_and_get_response(msg)

    # Check output directory
    if not (re_result := match_s3_path(event['output_dir'])):
        msg = f'got malformed S3 path for \'output_dir\':\n\t\'{event["output_dir"]}\''
        return log_error_and_get_response(msg)

    # Ensure arguments that must be ints are actually ints, if provided
    for arg_int in (arg for arg in arguments if arguments[arg].get('type_int')):
        if arg_int not in event:
            continue
        arg_value = event[arg_int]
        if isinstance(arg_value, int):
            continue
        if not arg_value.isdigit():
            msg = f'value for \'{arg_int}\' must be an integer, got:\n\t\'{arg_value}\''
            return log_error_and_get_response(msg)

    # Memory must be reasonable
    memory = int(event['instance_memory'])
    if memory > 100:
        msg = f'refusing to run with excessive memory request ({memory}GB), must run this manually'
        return log_error_and_get_response(msg)


def match_s3_path(s3_path):
    s3_path_re_str = r'''
        # Leading URI scheme name
        ^s3://

        # Bucket name
        (?P<bucket_name>[^/]+)/

        # Outer: match key
        # Inner: match final component; filename or directory name
        (?P<key>.*?(?P<key_name>[^/]+/?))$
    '''
    s3_path_re = re.compile(s3_path_re_str, re.VERBOSE)
    return s3_path_re.match(s3_path)


def check_s3_file_exists(bucket, key, error_store):
    s3_object = RESOURCE_S3.Object(bucket, key)
    try:
        s3_object.load()
    except botocore.exceptions.ClientError as e:
        error = e.response['Error']
        error_store.append((error['Code'], error['Message'], f's://{bucket}/{key}'))


def check_s3_output_dir_writable(output_dir):
    s3_path_components = match_s3_path(output_dir)
    bucket = s3_path_components['bucket_name']
    key = s3_path_components['key']
    try:
        key_test = f'{key}/permissions_test'
        CLIENT_S3.put_object(Body='perm_test', Bucket=bucket, Key=key_test)
        CLIENT_S3.delete_object(Bucket=bucket, Key=key_test)
    except botocore.exceptions.ClientError:
        msg = f'could not write to \'output_dir\' \'{output_dir}\''
        return log_error_and_get_response(msg)


def get_job_definition_arn(docker_image_tag):
    docker_image = f'{ERC_IMAGE_NAME}:{docker_image_tag}'
    if job_definition_arn := find_existing_job_definition(docker_image):
        return job_definition_arn
    else:
        return create_new_job_definition(docker_image_tag, docker_image)


def find_existing_job_definition(docker_image):
    # NOTE(SW): this should only ever find the revision created by CDK (unless others were not
    # correctly cleaned up)
    resp_job_defs = CLIENT_BATCH.describe_job_definitions(jobDefinitionName=JOB_DEFINITION_NAME)
    if not (job_defs := resp_job_defs.get('jobDefinitions')):
        msg = f'did not find definitions with job definition name \'{JOB_DEFINITION_NAME}\''
        return log_error_and_get_response(msg)
    job_defs = sorted(job_defs, key=lambda k: k['revision'], reverse=True)
    for job_def in job_defs:
        # Skip non-active defintions, cannot be used
        if job_def['status'] != 'ACTIVE':
            continue
        if job_def['containerProperties']['image'] == docker_image:
            return job_def['jobDefinitionArn']


def create_new_job_definition(docker_image_tag, docker_image):
    resp_erc_images = CLIENT_ERC.list_images(repositoryName=ERC_REPO_NAME)
    image_tags = {d.get('imageTag') for d in resp_erc_images.get('imageIds')}
    if not image_tags:
        msg = f'did not find any Docker image tags in \'{repo_name}\' repo'
        return log_error_and_get_response(msg)
    if docker_image_tag not in image_tags:
        tags_str = '\n\t'.join(image_tags)
        msg = f'docker image tag \'{docker_image_tag}\' not available, got:\n\t{tags_str}'
        return log_error_and_get_response(msg)
    resp_job_def = CLIENT_BATCH.register_job_definition(
        jobDefinitionName=JOB_DEFINITION_NAME,
        type='container',
        containerProperties={
            'image': docker_image,
            'command': ['true'],
            'memory': 1000,
            'vcpus': 1,
        }
    )
    return resp_job_def['jobDefinitionArn']


def log_error_and_get_response(error_msg, level='critical'):
    level_number = logging.getLevelName(level.upper())
    LOGGER.log(level_number, error_msg)
    return {
        'statusCode': 400,
        'body': error_msg
    }


def get_argument_string(arg_name, key, event):
    value = event.get(key)
    return f'--{arg_name} {value}' if value else ''


if __name__ == '__main__':
    main()
