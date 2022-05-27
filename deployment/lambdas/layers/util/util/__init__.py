import logging
import os
import re


import boto3
import libica.openapi.libgds
import libumccr.aws.libsm


ICA_ACCESS_TOKEN = None


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def get_environment_variable(name):
    """Get value of environment variable.

    :param str name: Name of environment variable
    :returns: Value of environment variable
    :rtype: str
    """
    if not (value := os.environ.get(name)):
        msg = f'could not find env variable {name}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return value


def get_ssm_parameter(name, client, decrypt=True):
    """Get value of SSM parameter.

    :param str name: Name of SSM parameter
    :param botocore.client.SSM client: boto3 SSM client
    :param bool decrypt: Decrypt SSM parameter value
    :returns: Value of SSM parameter
    :rtype: str
    """
    response = client.get_parameter(Name=name, WithDecryption=decrypt)
    if not (pm_data := response.get('Parameter')):
        msg = f'could not get SSM parameter {name}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return pm_data['Value']


def get_resource(service_name, region_name=None):
    """Get boto3 resource instance.

    :param str name: Service type
    :param str region_name: Name of region for service
    :returns: boto3 resource
    :rtype: boto3.resources.factory.*.ServiceResource
    """
    try:
        response = boto3.resource(service_name, region_name=region_name)
    except Exception as err:
        LOGGER.critical(f'could not get AWS resouce for {service_name}:\r{err}')
        raise err
    return response


def get_client(service_name, region_name=None):
    """Get boto3 client instance.

    :param str name: Client type
    :param str region_name: Name of region for service
    :returns: boto3 client
    :rtype: boto3.client.*
    """
    try:
        response = boto3.client(service_name, region_name=region_name)
    except Exception as err:
        LOGGER.critical(f'could not get AWS client for {service_name}:\r{err}')
        raise err
    return response


def get_context_info(context):
    """Collect information from Lambda context object.

    :param LambdaContext context: Lambda context
    :returns: Selected LambdaContext attributes
    :rtype: dict
    """
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


def match_remote_path(path):
    """Parse components of a GDS or S3 path.

    :param str s3_path: GDS or S3 path
    :returns: Regex match object containing parsed paths
    :rtype: re.Match
    """
    path_re_str = r'''
        # Leading URI scheme name
        ^(?:gds|s3)://

        # Bucket name
        (?P<bucket_name>[^/]+)/

        # Outer: match key
        # Inner: match final component; filename or directory name
        (?P<key>.*?(?P<key_name>[^/]+/?))$
    '''
    path_re = re.compile(path_re_str, re.VERBOSE)
    return path_re.match(path)


def get_libica_gds_configuration():
    """Create configuration for libica.libgds operations.

    :returns: Configuration for GDS operations
    :rtype: libica.openapi.libgds.Configuration
    """
    # pylint: disable=global-statement
    # Cache ICA access token to reduce number of AWS Secrets API calls
    global ICA_ACCESS_TOKEN
    if not ICA_ACCESS_TOKEN:
        ICA_ACCESS_TOKEN = libumccr.aws.libsm.get_secret('IcaSecretsPortal')
    return libica.openapi.libgds.Configuration(
        host='https://aps2.platform.illumina.com',
        api_key_prefix={'Authorization': 'Bearer'},
        api_key={'Authorization': ICA_ACCESS_TOKEN},
    )
