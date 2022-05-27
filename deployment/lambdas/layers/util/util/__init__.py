import logging
import re


import libica.openapi.libgds
import libumccr.aws.libsm


ICA_ACCESS_TOKEN = None


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


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
