#!/usr/bin/env python3
import json
import logging
import re
import urllib.parse


import requests
import aws_requests_auth.boto_utils


import util


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)

CLIENT_LAMBDA = util.get_client('lambda')

PORTAL_API_BASE_URL = util.get_environment_variable('PORTAL_API_BASE_URL')
SUBMISSION_LAMBDA_ARN = util.get_environment_variable('SUBMISSION_LAMBDA_ARN')
OUTPUT_BUCKET = util.get_environment_variable('OUTPUT_BUCKET')


def main(event, context):
    """Lambda entry point.

    Payload example:
    ```json
    {
        "subject_id": "SBJ01673_PRJ220789_L2200334",
        "tumor_sample_id": "PRJ000001",
        "normal_sample_id": "PRJ000002",
    }
    ```

    :params dict event: Event payload
    :params LambdaContext context: Lambda context
    :returns: None
    :rtype: None
    """
    # Log invocation data
    LOGGER.info(f'event: {json.dumps(event)}')
    LOGGER.info(f'context: {json.dumps(util.get_context_info(context))}')

    # Check inputs and ensure that output directory is writable
    validate_event_data(event)

    # Obtain IAM auth for API Gateway, required to sign HTTP API requests
    api_auth = aws_requests_auth.boto_utils.BotoAWSRequestsAuth(
        aws_host=urllib.parse.urlparse(PORTAL_API_BASE_URL).hostname,
        aws_region='ap-southeast-2',
        aws_service='execute-api',
    )

    # Get sample information
    if subject_id := event.get('subject_id'):
        subject_md_all = get_subject_metadata(subject_id, api_auth)
        tumor_sample_md, normal_sample_md = get_samples_from_subject_metadata(subject_md_all, subject_id)
    else:
        tumor_sample_md = get_sample_metadata(event['tumor_sample_id'], api_auth)
        normal_sample_md = get_sample_metadata(event['normal_sample_id'], api_auth)
        if tumor_sample_md['phenotype'] != 'tumor':
            msg = f'provided tumor sample ID has phenotype of {tumor_sample_md["phenotype"]}'
            LOGGER.critical(msg)
            raise ValueError(msg)
        if normal_sample_md['phenotype'] != 'normal':
            msg = f'provided normal sample ID has phenotype of {normal_sample_md["phenotype"]}'
            LOGGER.critical(msg)
            raise ValueError(msg)
        # Set subject ID
        assert tumor_sample_md['subject_id'] == normal_sample_md['subject_id']
        subject_id = tumor_sample_md['subject_id']

    # Check sample type; prevent runs using FFPE samples
    ffpe_samples = list()
    for md in (tumor_sample_md, normal_sample_md):
        if md['source'].lower() != 'ffpe':
            continue
        ffpe_samples.append(f'{md["sample_id"]} ({md["phenotype"]}) [{md["source"]}]')
    if ffpe_samples:
        plurality = 'FFPE samples' if len(ffpe_samples) > 1 else 'a FFPE sample'
        ffpe_samples_str = '\n\t'.join(ffpe_samples)
        msg = f'Got {plurality}, refusing to run:\n\t{ffpe_samples_str}'
        LOGGER.error(msg)
        raise ValueError(msg)

    data = get_submission_data(tumor_sample_md, normal_sample_md, subject_id, api_auth)
    LOGGER.debug(f'compiled submission data: {data}')

    # Invoke Lambda
    data_json = json.dumps(data)
    LOGGER.info(f'Invoking Lambda {SUBMISSION_LAMBDA_ARN} with {data_json}')
    response = CLIENT_LAMBDA.invoke(
        FunctionName=SUBMISSION_LAMBDA_ARN,
        Payload=data_json,
    )
    LOGGER.debug(f'got response: {response}')


def validate_event_data(event):
    """Validate arguments specified in Lambda event payload.

    :params dict event: Event payload
    :returns: None
    :rtype: None
    """
    # pylint: disable=superfluous-parens
    args_known = [
        'subject_id',
        'tumor_sample_id',
        'normal_sample_id',
    ]
    args_unknown = [arg for arg in event if arg not in args_known]
    if args_unknown:
        plurality = 'arguments' if len(args_unknown) > 1 else 'argument'
        args_unknown_str = '\r\t'.join(args_unknown)
        msg = f'got {len(args_unknown)} unknown {plurality}:\r\t{args_unknown_str}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    sample_id_provided = ('tumor_sampe_id' in event) or ('normal_sample_id' in event)
    subject_id_provided = 'subject_id' in event
    if not (subject_id_provided ^ sample_id_provided):
        msg = 'You must provide either \'subject_id\' or both \'tumor_sample_id\' and \'normal_sample_id\''
        LOGGER.critical(msg)
        raise ValueError(msg)


def get_file_path(pattern, file_list):
    """Find the filepath that matches a regex in a give list of filepaths.

    :params str pattern: Regular expression pattern
    :params list file_list: List of filepaths
    :returns: Filepath matching regex
    :rtype: str
    """
    # pylint: disable=unbalanced-tuple-unpacking
    LOGGER.info(f'getting file path with pattern {pattern}')
    regex = re.compile(pattern)
    files_matched = list()
    for filepath in file_list:
        if regex.match(filepath):
            files_matched.append(filepath)
    if len(files_matched) > 1:
        msg = f'found more than one entry for {pattern}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    if len(files_matched) == 0:
        msg = f'no entries found for {pattern}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    [filepath] = files_matched
    LOGGER.info(f'got file path {filepath} with pattern {pattern}')
    return filepath


def get_sample_metadata(sample_id, api_auth):
    """Obtain sample metadata from the data portal API.

    :params str sample_id: Sample identifier
    :params aws_requests_auth.boto_utils.BotoAWSRequestsAuth api_auth: API auth object
    :returns: Sample metadata entry
    :rtype: dict
    """
    LOGGER.info(f'getting sample metadata for {sample_id}')
    md_entries = make_api_get_call(f'metadata?sample_id={sample_id}', api_auth)
    if len(md_entries) != 1:
        msg = f'found more than one entry for {sample_id}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return md_entries[0]


def get_subject_metadata(subject_id, api_auth):
    """Obtain subject metadata from the data portal API.

    :params str subject_id: Subject identifier
    :params aws_requests_auth.boto_utils.BotoAWSRequestsAuth api_auth: API auth object
    :returns: Subject metadata entries
    :rtype: list
    """
    LOGGER.info(f'getting subject metadata for {subject_id}')
    return make_api_get_call(f'metadata?subject_id={subject_id}', api_auth)


def make_api_get_call(endpoint, auth):
    """Make a GET call to the data portal API.

    :params str endpoint: API endpoint
    :params aws_requests_auth.boto_utils.BotoAWSRequestsAuth api_auth: API auth object
    :returns: Resulting records
    :rtype: list
    """
    url = f'{PORTAL_API_BASE_URL}/iam/{endpoint}'
    LOGGER.debug(f'GET request to {url}')
    req_raw = requests.get(url, auth=auth)
    req = req_raw.json()
    LOGGER.debug(f'recieved {req} from {url}')
    # Check we have results
    if not (entries := req.get('results')):
        msg = f'no results found for query {url}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    # Ensure we have pagination data but fail if we have multiple pages
    # NOTE(SW): will need an example case to implement logic to handle
    if not (pg_data := req.get('pagination')):
        msg = f'no pagination data recieved {url} query'
        LOGGER.critical(msg)
        raise ValueError(msg)
    if pg_data['count'] > pg_data['rowsPerPage']:
        msg = f'recieved multiple pages for {url} query, refusing to handle'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return entries


def get_samples_from_subject_metadata(subject_md_all, subject_id):
    """Collect tumor and normal samples from subject metadata entries.

    :params list subject_md_all: Subject metadata entries
    :params str subject_id: Subject identifier
    :returns: Tumor and normal sample metadata
    :rtype: tuple
    """
    subject_md = dict()
    for entry in subject_md_all:
        if entry['type'] != 'WGS':
            continue
        assert entry['sample_id'] not in subject_md
        subject_md[entry['sample_id']] = entry
    if len(subject_md) != 2:
        sdata = list()
        for md in subject_md.values():
            sdata.append(f'{md["sample_id"]} ({md["phenotype"]})')
        sdata_str = '\n\t'.join(sdata)
        plurality = 'entry' if len(subject_md) == 1 else 'entries'
        msg = (
            f'found {len(subject_md)} WGS sample {plurality} for {subject_id} but can only proceed '
            f'using --subject_id with exactly two. Try again using --tumor_sample_id and '
            f'--normal_sample_id. Samples found using --subject_id:\n\t{sdata_str}'
        )
        LOGGER.critical(msg)
        raise ValueError(msg)
    tumor_sample_md = get_sample_from_phenotype(subject_md, 'tumor', subject_id)
    normal_sample_md = get_sample_from_phenotype(subject_md, 'normal', subject_id)
    return tumor_sample_md, normal_sample_md


def get_sample_from_phenotype(d, phenotype, subject_id):
    """Get sample of specified phenotype from a subject metadata entry.

    :params dict d: Subject metadata entry
    :params str phenotype: Sample phenotype
    :params str subject_id: Subject identifier
    :returns: Sample metadata entry
    :rtype: dict
    """
    samples = list()
    for e in d.values():
        if e['phenotype'] == phenotype:
            samples.append(e)
    if len(samples) > 1:
        msg = f'found multiple {phenotype} samples for {subject_id}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    if not samples:
        msg = f'no {phenotype} samples found for {subject_id}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return samples[0]


def get_submission_data(tumor_sample_md, normal_sample_md, subject_id, api_auth):
    """Collect the required data to submit a GPL job.

    :params dict tumor_sample_md: Tumor sample metadata
    :params dict normal_sample_md: Normal sample metadata
    :params str subject_id: Subject identifier
    :params aws_requests_auth.boto_utils.BotoAWSRequestsAuth api_auth: API auth object
    :returns: Payload for job submission
    :rtype: dict
    """
    # Set identifer
    identifier = f'{tumor_sample_md["project_owner"]}-{tumor_sample_md["project_name"]}_{subject_id}'
    # Get input file paths
    # NOTE(SW): the `/iam/s3` endpoint does not currently allow certain special characters (e.g.
    # '$' and '+') in the pattern string. So we must retrieve a list of all BAMs and VCFs from the
    # data portal for the subject and then manually collect the desired file with regex.
    file_list = [
        *get_subject_files(subject_id, '.bam', api_auth),
        *get_subject_files(subject_id, '.vcf.gz', api_auth),
    ]
    # NOTE(SW): some files are not uniquely named between multiple runs (e.g. normal BAM, manta VCF)
    # so we must select the desired run directory to obtain required files. The tumor BAM filename
    # is inherently unique across runs under the assumption that there are no run duplications. So
    # we obtain the correct run directory from the tumor BAM filepath and filter the input file
    # list.
    tumor_bam = get_file_path(get_bam_pattern(tumor_sample_md), file_list)
    date_dirname = get_date_dirname(tumor_bam)
    file_list_date_dir = [fp for fp in file_list if date_dirname in fp]
    # Collect remaining files
    normal_bam = get_file_path(get_bam_pattern(normal_sample_md), file_list_date_dir)
    tumor_smlv_vcf = get_file_path(fr'^.+{subject_id}-[^-]+-annotated.vcf.gz$', file_list_date_dir)
    tumor_sv_vcf = get_file_path(fr'^.+{subject_id}-manta.vcf.gz$', file_list_date_dir)
    # Set output directory using tumor BAM path
    if not (re_result := re.match(r'^s3://[^/]+/(.+?)/final/.+$', tumor_bam)):
        msg = (
            f'found non-standard input directory for tumor BAM ({tumor_bam}), refusing to guess '
            f' output directory please use manual submission'
        )
        LOGGER.critical(msg)
        raise ValueError(msg)

    output_prefix_base = re_result.group(1)
    if not re.match('^.+/[0-9]{4}-[0-9]{2}-[0-9]{2}$', output_prefix_base):
        msg = (
            f'could not obtain an appropriate output directory base from the tumor BAM ({tumor_bam}),'
            f' expected a \'date\' directory (YYYY-MM-DD) but got {output_prefix_base}'
        )
        LOGGER.critical(msg)
        raise ValueError(msg)
    output_dir = f's3://{OUTPUT_BUCKET}/{output_prefix_base}/gridss_purple_linx/'
    # Create and return submission data dict
    return {
        'job_name': f'gpl_{identifier}',
        'tumor_name': f'{subject_id}_{tumor_sample_md["sample_id"]}_{tumor_sample_md["library_id"]}',
        'normal_name': f'{subject_id}_{normal_sample_md["sample_id"]}_{normal_sample_md["library_id"]}',
        'tumor_bam': tumor_bam,
        'normal_bam': normal_bam,
        'tumor_smlv_vcf': tumor_smlv_vcf,
        'tumor_sv_vcf': tumor_sv_vcf,
        'output_dir': output_dir,
    }


def get_bam_pattern(md):
    """Construct regex for input BAM filepath.

    :params dict md: Sample metadata
    :returns: BAM regex
    :rtype: str
    """
    return fr'^.+/{md["subject_id"]}_{md["sample_id"]}_{md["library_id"]}-ready.bam$'


def get_subject_files(subject_id, pattern, api_auth):
    """Get a list of files associated with a subject.

    :params str subject_id: Subject identifier
    :params str pattern: Regular expression
    :params aws_requests_auth.boto_utils.BotoAWSRequestsAuth api_auth: API auth object
    :returns: Filepaths associated with the given subject
    :rtype: list
    """
    entries_all = make_api_get_call(f's3?subject={subject_id}&search={pattern}&rowsPerPage=1000', api_auth)
    filepaths = list()
    for entry in entries_all:
        filepaths.append(f's3://{entry["bucket"]}/{entry["key"]}')
    return filepaths


def get_date_dirname(fp):
    """Determine root path of a so called 'date directory'.

    :params str fp: Filepath containing the data directory
    :returns: Date directory root path
    :rtype: str
    """
    if not (regex_result := re.match('^.+/WGS/([0-9]{4}-[0-9]{2}-[0-9]{2})/final/.+$', fp)):
        msg = f'could not obtain required date directory from the tumor BAM: {fp}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return regex_result.group(1)
