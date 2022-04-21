import logging
import os


import boto3


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def get_environment_variable(name):
    if not (value := os.environ.get(name)):
        msg = f'could not find env variable {name}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return value


def get_ssm_parameter(name, client, decrypt=True):
    response = client.get_parameter(Name=name, WithDecryption=decrypt)
    if not (pm_data := response.get('Parameter')):
        msg = f'could not get SSM parameter {name}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return pm_data['Value']


def get_resource(service_name, region_name=None):
    try:
        response = boto3.resource(service_name, region_name=region_name)
    except Exception as err:
        LOGGER.critical(f'could not get AWS resouce for {service_name}:\r{err}')
        raise err
    return response


def get_client(service_name, region_name=None):
    try:
        response = boto3.client(service_name, region_name=region_name)
    except Exception as err:
        LOGGER.critical(f'could not get AWS client for {service_name}:\r{err}')
        raise err
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
