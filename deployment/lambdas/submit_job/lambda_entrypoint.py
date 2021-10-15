#!/usr/bin/env python3
import json
import logging
import os
import re
import sys


import boto3
import botocore


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def get_environment_variable(name):
    if not (value := os.environ.get(name)):
        LOGGER.critical(f'could not find env variable {name}')
        sys.exit(1)
    return value


def get_resource(service_name, region_name=None):
    try:
        response = boto3.resource(service_name, region_name=region_name)
    except Exception as err:
        LOGGER.critical(f'could not get AWS resouce for {service_name}:\r{err}')
        sys.exit(1)
    return response


def get_client(service_name, region_name=None):
    try:
        response = boto3.client(service_name, region_name=region_name)
    except Exception as err:
        LOGGER.critical(f'could not get AWS client for {service_name}:\r{err}')
        sys.exit(1)
    return response


def get_context_info(context):
    attributes = {
        'function_name',
        'function_version',
        'invoked_function_arn',
        'memory_limit_in_mb',
        'aws_request_id',
        'log_group_name',
        'log_stream_name',
    }
    return {attr: getattr(context, attr) for attr in attributes}


#SLACK_NOTIFY = get_environment_variable('SLACK_NOTIFY')
#SLACK_HOST = get_environment_variable('SLACK_HOST')
#SLACK_CHANNEL = get_environment_variable('SLACK_CHANNEL')
REFERENCE_DATA = get_environment_variable('REFERENCE_DATA')
BATCH_QUEUE_NAME = get_environment_variable('BATCH_QUEUE_NAME')
JOB_DEFINITION_ARN = get_environment_variable('JOB_DEFINITION_ARN')

CLIENT_BATCH = get_client('batch')
CLIENT_S3 = get_client('s3')
RESOURCE_S3 = get_resource('s3')

FILE_EXTENSIONS = {
    'bam': {'bam'},
    'vcf': {'vcf', 'vcf.gz'},
}


def main(event, context):
    # Log invocation data
    LOGGER.info(f'event: {json.dumps(event)}')
    LOGGER.info(f'context: {json.dumps(get_context_info(context))}')

    # Check inputs and ensure that output directory is writable
    if response_error := validate_event_data(event):
        return response_error
    if response_error := check_s3_output_dir_writable(event['output_dir']):
        return response_error

    # Construct command
    tumour_smlv_vcf_fp_arg = get_argument_string('tumour_smlv_vcf_fp', 'tumour_smlv_vcf', event)
    tumour_sv_vcf_fp_arg = get_argument_string('tumour_sv_vcf_fp', 'tumour_sv_vcf', event)
    gridss_jvmheap_arg = get_argument_string('gridss_jvmheap', 'gridss_jvmheap', event)
    annotate_gridss_calls_arg = '--annotate_gridss_calls' if 'annotate_gridss_calls' in event else ''
    command = f'''
        /opt/gpl/run_gpl.py
            --tumour_name {event["tumour_name"]}
            --normal_name {event["normal_name"]}
            --tumour_bam_fp {event["tumour_bam"]}
            --normal_bam_fp {event["normal_bam"]}
            {tumour_smlv_vcf_fp_arg}
            {tumour_sv_vcf_fp_arg}
            --reference_data {REFERENCE_DATA}
            --output_dir {event["output_dir"]}
            {annotate_gridss_calls_arg}
            {gridss_jvmheap_arg}
            --cpu_count {event["instance_vcpus"]}
    '''
    command = re.sub(r'[ \n]+', ' ', command).strip()
    command_full = ['bash', '-o', 'pipefail', '-c', command]

    # Submit job
    if not (job_name := event.get('job_name')):
        job_name = f'gpl__{event["tumour_name"]}__{event["normal_name"]}'
    instance_memory = int(event['instance_memory']) * 1000
    instance_vcpus = int(event['instance_vcpus'])
    response_job = CLIENT_BATCH.submit_job(
        jobName=job_name,
        jobQueue=BATCH_QUEUE_NAME,
        jobDefinition=JOB_DEFINITION_ARN,
        containerOverrides={
            'memory': instance_memory,
            'vcpus': instance_vcpus,
            'command': command_full,
        }
    )
    if not (job_id := response_job.get('jobId')):
        msg = f'could not get jobId from Batch job submission response: {response_job}'
        return log_error_and_get_response(msg, level='critical')
    return {
        'statusCode': 200,
        'body': f'submitted job id: {job_id}'
    }


def validate_event_data(event):
    arguments = {
        'job_name':                 {'required': False},
        'tumour_name':              {'required': True},
        'normal_name':              {'required': True},
        'tumour_bam':               {'required': True,  's3_input': True, 'filetype': 'bam'},
        'normal_bam':               {'required': True,  's3_input': True, 'filetype': 'bam'},
        # NOTE(SW): PURPLE currently requires tumour small variant VCF, forcing here
        'tumour_smlv_vcf':          {'required': True,  's3_input': True, 'filetype': 'vcf'},
        'tumour_sv_vcf':            {'required': False, 's3_input': True, 'filetype': 'vcf'},
        'output_dir':               {'required': True},
        'annotate_gridss_calls':    {'required': False},
        'gridss_jvmheap':           {'required': False, 'type_int': True, 'default': 26},
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

    # Disallow setting jvmheap greater than requested memory
    gridss_jvmheap = int(event['gridss_jvmheap'])
    if gridss_jvmheap >= (memory - 2):
        msg_p1 = f'refusing to run without at least a 2GB buffer between \'gridss_jvmheap\''
        msg_p2 = f'({gridss_jvmheap}GB) and \'instance_memory\' ({memory}GB). Please set'
        msg_p3 = f'\'instance_memory\' to at least {gridss_jvmheap + 2}GB or reduce \'gridss_jvmheap\''
        msg = f'{msg_p1} {msg_p2} {msg_p3}'
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
