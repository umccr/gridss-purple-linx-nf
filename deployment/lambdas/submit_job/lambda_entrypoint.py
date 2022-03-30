#!/usr/bin/env python3
import argparse
import json
import logging
import os
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
    # Log invocation data
    LOGGER.info(f'event: {json.dumps(event)}')
    LOGGER.info(f'context: {json.dumps(util.get_context_info(context))}')

    # Check inputs and ensure that output directory is writable
    if response_error := validate_event_data(event):
        return response_error

    # Obtain IAM auth for API Gateway, required to sign HTTP API requests
    api_auth = aws_requests_auth.boto_utils.BotoAWSRequestsAuth(
        aws_host=urllib.parse.urlparse(PORTAL_API_BASE_URL).hostname,
        aws_region='ap-southeast-2',
        aws_service='execute-api',
    )

    # Get sample information
    if (subject_id := event.get('subject_id')):
        subject_md_all = get_subject_metadata(subject_id, api_auth)
        tumor_sample_md, normal_sample_md = get_samples_from_subject_metadata(
            subject_md_all,
            subject_id
        )
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

    # Submission data
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
    args_known = [
        'subject_id',
        'tumor_sample_id',
        'normal_sample_id',
    ]
    args_unknown = [arg for arg in event if arg not in args_known]
    if args_unknown:
        plurality = 'arguments' if len(args_unknown) > 1 else 'argument'
        args_unknown_str = '\r\t'.join(args_unknown)
        msg = f'got {len(args_unknown)} unknown arguments:\r\t{args_unknown_str}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    sample_id_provided = ('tumor_sampe_id' in event) or ('normal_sample_id' in event)
    subject_id_provided = 'subject_id' in event
    if not (subject_id_provided ^ sample_id_provided):
        msg = 'You must provide either \'subject_id\' or both \'tumor_sample_id\' and \'normal_sample_id\''
        LOGGER.critical(msg)
        raise ValueError(msg)


def get_file_path(pattern, file_list):
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
    elif len(files_matched) == 0:
        msg = f'no entries found for {pattern}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    [filepath] = files_matched
    LOGGER.info(f'got file path {filepath} with pattern {pattern}')
    return filepath


def get_sample_metadata(sample_id, api_auth):
    LOGGER.info(f'getting sample metadata for {sample_id}')
    md_entries = make_api_get_call(f'metadata?sample_id={sample_id}', api_auth)
    if len(md_entries) != 1:
        msg = f'found more than one entry for {sample_id}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return md_entries[0]


def get_subject_metadata(subject_id, api_auth):
    LOGGER.info(f'getting subject metadata for {subject_id}')
    return make_api_get_call(f'metadata?subject_id={subject_id}', api_auth)


def make_api_get_call(endpoint, auth):
    url = f'{PORTAL_API_BASE_URL}/iam/{endpoint}'
    LOGGER.debug(f'GET request to {url}')
    req_md_raw = requests.get(url, auth=auth)
    req_md = req_md_raw.json()
    LOGGER.debug(f'recieved {req_md} from {url}')
    # Check we have results
    if not (md_entries := req_md.get('results')):
        msg = f'no results found for query {url}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    # Ensure we have pagination data but fail if we have multiple pages
    # NOTE(SW): will need an example case to implement logic to handle
    if not (pg_data := req_md.get('pagination')):
        msg = f'no pagination data recieved for {subject_id} metadata query'
        LOGGER.critical(msg)
        raise ValueError(msg)
    if pg_data['count'] > pg_data['rowsPerPage']:
        msg = f'recieved multiple pages for {subject_id} metadata query, refusing to handle'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return md_entries


def get_samples_from_subject_metadata(subject_md_all, subject_id):
    subject_md = dict()
    for entry in subject_md_all:
        if entry['type'] != 'WGS':
            continue
        assert entry['sample_id'] not in subject_md
        subject_md[entry['sample_id']] = entry
    if len(subject_md) != 2:
        subject_ids = '\r\t'.join(subject_md)
        plurality = 'entry' if len(subject_md) == 1 else 'entries'
        msg = (
            f'found {len(subject_md)} WGS sample {plurality} for {subject_id} but can only proceed '
            f'using --subject_id with exactly two. Try again using --tumor_sample_id and '
            f'--normal_sample_id. Samples found using --subject_id: {", ".join(subject_md)}.'
        )
        LOGGER.critical(msg)
        raise ValueError(msg)
    tumor_sample_md = get_sample_from_phenotype(subject_md, 'tumor', subject_id)
    normal_sample_md = get_sample_from_phenotype(subject_md, 'normal', subject_id)
    return tumor_sample_md, normal_sample_md


def get_sample_from_phenotype(d, phenotype, subject_id):
    samples = list()
    for e in d.values():
        if e['phenotype'] == phenotype:
            samples.append(e)
    if len(samples) > 1:
        msg = f'found multiple {phenotype} samples for {subject_id}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    elif not samples:
        msg = f'no {phenotype} samples found for {subject_id}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return samples[0]


def get_submission_data(tumor_sample_md, normal_sample_md, subject_id, api_auth):
    # Set identifers
    identifier = f'{tumor_sample_md["project_owner"]}-{tumor_sample_md["project_name"]}_{subject_id}'
    tumor_name = f'{subject_id}_{tumor_sample_md["sample_id"]}_{tumor_sample_md["library_id"]}'
    normal_name = f'{subject_id}_{normal_sample_md["sample_id"]}_{normal_sample_md["library_id"]}'
    # Get input file paths
    # NOTE(SW): the `/iam/s3` endpoint does not currently allow certain special characters (e.g.
    # '$' and '+') in the pattern string. So we must retrieve a list of all BAMs and VCFs from the
    # data portal for the subject and then manually collect the desired file with regex.
    file_list = [
        *get_subject_files(subject_id, '.bam', api_auth),
        *get_subject_files(subject_id, '.vcf.gz', api_auth),
    ]
    tumor_bam = get_file_path(get_bam_pattern(tumor_sample_md), file_list)
    normal_bam = get_file_path(get_bam_pattern(normal_sample_md), file_list)
    tumor_smlv_vcf = get_file_path(fr'^.+{subject_id}-[^-]+-annotated.vcf.gz$', file_list)
    tumor_sv_vcf = get_file_path(fr'^.+{subject_id}-manta.vcf.gz$', file_list)
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
    return fr'^.+/{md["subject_id"]}_{md["sample_id"]}_{md["library_id"]}-ready.bam$'


def get_subject_files(subject_id, pattern, api_auth):
    entries_all = make_api_get_call(f's3?subject={subject_id}&search={pattern}&rowsPerPage=1000', api_auth)
    filepaths = list()
    for entry in entries_all:
        filepaths.append(f's3://{entry["bucket"]}/{entry["key"]}')
    return filepaths
