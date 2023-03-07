import base64
import datetime
import json
import logging
import re


import libica.openapi.libgds
import libumccr.aws.libsm


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
    # The libumccr.aws.libsm.get_secret function result is cached and must be cleared if the JWT
    # token has expired in order to obtain a new valid token
    ica_access_token = libumccr.aws.libsm.get_secret('IcaSecretsPortal')
    if time_until_token_expiry(ica_access_token) <= datetime.timedelta(hours=1):
        libumccr.aws.libsm.get_secret.cache_clear()
        ica_access_token = libumccr.aws.libsm.get_secret('IcaSecretsPortal')
    return libica.openapi.libgds.Configuration(
        host='https://aps2.platform.illumina.com',
        api_key_prefix={'Authorization': 'Bearer'},
        api_key={'Authorization': ica_access_token},
    )


def time_until_token_expiry(token):
    """Get time remaining until token expiry.

    :param str token: Base64 encoded JWT token
    :returns: Time until expiry
    :rtype: datetime.datetime.timedelta
    """
    token_parts = token.split('.')
    assert len(token_parts) == 3
    padding = '=' * (len(token_parts[1]) % 4)
    payload_str = base64.b64decode(token_parts[1] + padding)
    payload = json.loads(payload_str)
    expiry = datetime.datetime.fromtimestamp(payload['exp'])
    return expiry - datetime.datetime.now()
