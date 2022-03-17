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
OUTPUT_PREFIX = util.get_environment_variable('OUTPUT_PREFIX')
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


def get_file_path(pattern, subject_id, api_auth):
    LOGGER.info(f'getting file path for {subject_id} with pattern {pattern}')
    md_entries_all = make_api_get_call(f's3?subject={subject_id}&search={pattern}', api_auth)
    if len(md_entries_all) == 0:
        return str()
    # The data portal /s3 endpoint doesn't use standard regex to match, and in some cases the
    # germline smlv VCF was selected. Forcing all files to match regex to prevent unwanted file
    # selection.
    md_entries = list()
    for md_entry in md_entries_all:
        if not (re_result := re.search(pattern, md_entry['key'])):
            continue
        md_entries.append(md_entry)
    if len(md_entries) > 1:
        msg = f'found more than one entry for {pattern}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    elif len(md_entries) == 0:
        msg = f'no entries found for {pattern}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    entry = md_entries[0]
    filepath = f's3://{entry["bucket"]}/{entry["key"]}'
    LOGGER.info(f'got file path {filepath} for {subject_id} with pattern {pattern}')
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
    url = f'{PORTAL_API_BASE_URL}/{endpoint}'
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
    identifier = f'{tumor_sample_md["project_owner"]}-{tumor_sample_md["project_name"]}_{subject_id}'
    bam_tumor_pattern = get_bam_pattern(tumor_sample_md)
    bam_normal_pattern = get_bam_pattern(normal_sample_md)
    tumor_smlv_vcf_pattern = f'{subject_id}-[^-]+-annotated.vcf.gz$'
    tumor_sv_vcf_pattern = f'{subject_id}-manta.vcf.gz$'
    tumor_name = f'{subject_id}_{tumor_sample_md["sample_id"]}_{tumor_sample_md["library_id"]}'
    normal_name = f'{subject_id}_{normal_sample_md["sample_id"]}_{normal_sample_md["library_id"]}'
    output_base_dir = f's3://{OUTPUT_BUCKET}/{OUTPUT_PREFIX}/runs'
    return {
        'job_name': f'gpl_shortcut_{identifier}',
        'tumor_name': f'{subject_id}_{tumor_sample_md["sample_id"]}_{tumor_sample_md["library_id"]}',
        'normal_name': f'{subject_id}_{normal_sample_md["sample_id"]}_{normal_sample_md["library_id"]}',
        'tumor_bam': get_file_path(bam_tumor_pattern, subject_id, api_auth),
        'normal_bam': get_file_path(bam_normal_pattern, subject_id, api_auth),
        'tumor_smlv_vcf': get_smlv_vcf_file_path(smlv_vcf_pattern, subject_id, api_auth),
        'tumor_sv_vcf': get_file_path(tumor_sv_vcf_pattern, subject_id, api_auth),
        'output_dir': f'{output_base_dir}/{identifier}_shortcut/',
    }


def get_bam_pattern(md):
    return f'{md["subject_id"]}_{md["sample_id"]}_{md["library_id"]}-ready.bam$'


def get_smlv_vcf_file_path(pattern, subject_id, api_auth):
    filepath = get_file_path(f'{subject_id}-[^-]+-annotated.vcf.gz$', subject_id, api_auth)
    if '-germline-' in filepath:
        msg = f'expected a somatic VCF but got germline with {pattern}'
        LOGGER.critical(msg)
        raise ValueError(msg)
    return filepath
