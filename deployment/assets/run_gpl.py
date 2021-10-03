#!/usr/bin/env python3
import argparse
import gzip
import io
import logging
import pathlib
import re
import signal
import subprocess
import sys
import textwrap


import boto3


logging.basicConfig()
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)


# Local input
ROOT_LOCAL_DIR = pathlib.Path('.')
DATA_LOCAL_DIR = ROOT_LOCAL_DIR / 'data/'
REFERENCE_LOCAL_DIR = DATA_LOCAL_DIR / 'reference/'
SAMPLE_LOCAL_DIR = DATA_LOCAL_DIR / 'sample/'
# Local output
OUTPUT_LOCAL_DIR = ROOT_LOCAL_DIR / 'output/'
NEXTFLOW_DIR = OUTPUT_LOCAL_DIR / 'nextflow/'
WORK_DIR = NEXTFLOW_DIR / 'work/'
# Remote output
# NOTE(SW): defined as global from get_arguments(), see note therein
OUTPUT_DIR = str()


# NOTE(SW): check that output_dir is writable S3 path before running pipeline


# Repeated
def get_client(service_name, region_name=None):
    try:
        response = boto3.client(service_name, region_name=region_name)
    except Exception as err:
        LOGGER.critical(f'could not get AWS client for {service_name}:\r{err}')
        sys.exit(1)
    return response


# Repeated
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


CLIENT_S3 = get_client('s3')


def get_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sample_name', required=True,
            help='Sample name')
    parser.add_argument('--tumour_name', required=True,
            help='Tumour name as if appears in VCFs')
    parser.add_argument('--normal_name', required=True,
            help='Normal name as if appears in VCFs')
    parser.add_argument('--tumour_bam_fp', required=True,
            help='Tumour BAM S3 path')
    parser.add_argument('--normal_bam_fp', required=True,
            help='Normal BAM S3 path')
    parser.add_argument('--tumour_smlv_vcf_fp', required=False,
            help='Tumour small variant VCF S3 path')
    parser.add_argument('--tumour_sv_vcf_fp', required=False,
            help='Tumour structural variant VCF S3 path (generally Manta calls)')
    parser.add_argument('--reference_data', required=True,
            help='Reference data directory S3 path')
    parser.add_argument('--output_dir', required=True,
            help='Output S3 path')
    parser.add_argument('--annotate_gridss_calls', required=False, action='store_true',
            help='Enable GRIDSS annotation of SVs using RepeatMasker')
    parser.add_argument('--gridss_jvmheap', type=int, required=False, default=26,
            help='Memory to allocate for applicable GRIDSS steps')
    args = parser.parse_args()
    # NOTE(SW): set OUTPUT_DIR as a global here to simplify calling upload_file from handle_signal.
    # Alternatively, the handle_signal would need to be defined in a scope where output_dir is
    # defined.
    global OUTPUT_DIR
    OUTPUT_DIR = args.output_dir
    delattr(args, 'output_dir')
    return args


def main():
    # Use user-defined function to handle signals; upload log and config files upon unexpected
    # termination. After upload complete/attempted, default signal handler is invoked.
    for s in signal.valid_signals():
        if signal.getsignal(s) is not signal.Handlers.SIG_DFL:
            continue
        if s in {signal.SIGKILL, signal.SIGSTOP, signal.SIGCHLD}:
            continue
        signal.signal(s, handle_signal)

    # Get command line arguments
    args = get_arguments()

    # Ensure we have matching sample names in VCFs; stream and decompress to retrieve VCF header,
    # then compare VCF sample column names to input sample names
    # Tumour small variants VCF
    if args.tumour_smlv_vcf_fp:
        tumour_smlv_sample_names_input = (('tumour', args.tumour_name), ('normal', args.normal_name))
        check_vcf_sample_names(tumour_smlv_sample_names_input, args.tumour_smlv_vcf_fp)
    # Tumour structural variants VCF
    if args.tumour_sv_vcf_fp:
        tumour_sv_sample_names_input = (('tumour', args.tumour_name), ('normal', args.normal_name))
        check_vcf_sample_names(tumour_sv_sample_names_input, args.tumour_sv_vcf_fp)

    # Pull data - sample (including BAM indices) and then reference
    # This is decoupled from Nextflow to ease debugging and transparency for errors related to this
    # operation.
    sample_data_local_paths = pull_sample_data(
        args.tumour_bam_fp,
        args.normal_bam_fp,
        args.tumour_smlv_vcf_fp,
        args.tumour_sv_vcf_fp
    )
    execute_command(f'aws s3 sync {args.reference_data} {REFERENCE_LOCAL_DIR}')

    # Create nextflow configuration file
    # Pack settings into dict for readability
    config_settings = {
        'sample_name': args.sample_name,
        'tumour_name': args.tumour_name,
        'normal_name': args.normal_name,
        'annotate_gridss_calls': 'true' if args.annotate_gridss_calls else 'false',
        'gridss_jvmheap': args.gridss_jvmheap,
        'sample_data_local_paths': sample_data_local_paths,
    }
    # Create and write config
    config_fp = NEXTFLOW_DIR / 'nextflow.config'
    config_blob = get_config(config_settings)
    if not config_fp.parent.exists():
        config_fp.parent.mkdir(parents=True)
    with config_fp.open('w') as fh:
        fh.write(config_blob)

    # Run pipeline
    log_fp = NEXTFLOW_DIR / 'nextflow_log.txt'
    command = f'nextflow -log {log_fp} run -config {config_fp} -work-dir {WORK_DIR} /opt/gpl/pipeline/main.nf'
    execute_command(command)

    # Upload results
    upload_data_outputs()


def check_vcf_sample_names(sample_names_input, vcf_fp):
    # Get and the match sample names
    sample_names_vcf = get_samples_from_vcf_header(vcf_fp)
    sample_name_missing = list()
    for sample_name_type, sample_name_input in sample_names_input:
        if sample_name_input in sample_names_vcf:
            msg = f'found {sample_name_type} sample \'{sample_name_input}\' in \'{vcf_fp}\''
            LOGGER.info(msg)
        else:
            sample_name_missing.append(f'{sample_name_type}: {sample_name_input}')
    # Check for unexpected number of VCF sample names
    sample_name_errors = list()
    if len(sample_names_vcf) != len(sample_names_input):
        msg_p1 = f'expected {len(sample_names_input)} sample names in \'{vcf_fp}\','
        msg_p2 = f'got {len(sample_names_vcf)}'
        msg = f'{msg_p1} {msg_p2}'
        if len(sample_names_vcf) == 0:
            sample_name_errors.append(msg)
        else:
            sample_names_str = '\n\t'.join(sample_names_vcf)
            sample_name_errors.append(f'{msg}:\n\t{sample_names_str}')
    # Report unmatched sample names
    # NOTE(SW): this section is not clean, fix when there is time
    if sample_name_missing:
        if len(sample_names_vcf) == 0:
            sample_names_vcf_str = '<none found>'
        else:
            sample_names_vcf_str = '\n\t\t'.join(sample_names_vcf)
        sample_names_missing_str = '\n\t\t'.join(sample_name_missing)
        plurality = 'names' if len(sample_name_missing) > 1 else 'name'
        msg_p1 = f'could not find {len(sample_name_missing)} sample {plurality} in'
        msg_p2 = f'\'{vcf_fp}\', got:\n\tVCF sample names:\n\t\t{sample_names_vcf_str}'
        msg_p3 = f'\n\tUnmatched input sample {plurality}:\n\t\t{sample_names_missing_str}'
        LOGGER.critical(f'{msg_p1} {msg_p2}{msg_p3}')
    # Report unexpected number of VCF sample names
    if sample_name_errors:
        for sample_name_error in sample_name_errors:
            LOGGER.critical(sample_name_error)
    # Exit on any error
    if sample_name_errors or sample_name_missing:
        sys.exit(1)


def get_samples_from_vcf_header(vcf_s3_path):
    # Get a file stream and chunk iterator for the VCF
    s3_path_components = match_s3_path(vcf_s3_path)
    response = CLIENT_S3.get_object(
        Bucket=s3_path_components['bucket_name'],
        Key=s3_path_components['key'],
    )
    file_stream = response['Body']
    file_chunk_iter = file_stream.iter_chunks()
    # Iterate and decompress chunks until we get the header line
    data_raw = b''
    while True:
        data_raw += next(file_chunk_iter)
        data_lines = decompress_gzip_chunks(data_raw)
        if header_line := get_header_line(data_lines):
            break
    # Remove first nine columns, assuming leading columns are:
    # #CHROM POS ID REF ALT QUAL FILTER INFO FORMAT
    header_tokens = header_line.rstrip().split('\t')
    sample_list = header_tokens[9:]
    return sample_list


def get_header_line(data_lines):
    for line in data_lines:
        if not line.startswith('#'):
            raise ValueError('running past header without finding header line')
        elif line.startswith('#CHROM'):
            return line


def decompress_gzip_chunks(data):
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode='r') as fh:
        try:
            lines = list()
            for line_bytes in fh:
                lines.append(line_bytes.decode())
        except EOFError:
            pass
    return lines


def pull_sample_data(tumour_bam_fp, normal_bam_fp, tumour_smlv_vcf_fp, tumour_sv_vcf_fp):
    # Set files to pull; add BAM indexes (required for AMBER, COBALT, GRIDSS read extraction)
    s3_paths = {
        'tumour_bam_fp': tumour_bam_fp,
        'normal_bam_fp': normal_bam_fp,
        'tumour_bam_index_fp': f'{tumour_bam_fp}.bai',
        'normal_bam_index_fp': f'{normal_bam_fp}.bai',
    }
    if tumour_smlv_vcf_fp:
        s3_paths['tumour_smlv_vcf_fp'] = tumour_smlv_vcf_fp
    if tumour_sv_vcf_fp:
        s3_paths['tumour_sv_vcf_fp'] = tumour_sv_vcf_fp
    # Download files
    local_paths = dict()
    for input_type, s3_path in s3_paths.items():
        s3_path_components = match_s3_path(s3_path)
        local_path = SAMPLE_LOCAL_DIR / s3_path_components['key_name']
        local_paths[input_type] = local_path
        execute_command(f'aws s3 cp {s3_path} {SAMPLE_LOCAL_DIR}/')
    return local_paths


def execute_command(command):
    LOGGER.debug(f'executing: {command}')
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        encoding='utf-8'
    )
    if result.returncode != 0:
        LOGGER.critical(f'Failed to run command: {result.args}')
        LOGGER.critical(f'stdout: {result.stdout}')
        LOGGER.critical(f'stderr: {result.stderr}')
        upload_data_outputs(ignore_work_dir_symlinks=False)
        sys.exit(1)
    return result


def get_config(config_settings):
    config_params = get_config_params(config_settings)
    config_misc = get_config_misc()
    config_lines = [
        'params {',
        config_params,
        '}',
        config_misc,
    ]
    return '\n'.join(config_lines)


def get_config_params(config_settings):
    sample_data_local_paths = config_settings['sample_data_local_paths']
    config_params_input_lines = [
        '// Input',
        f'sample_name = \'{config_settings["sample_name"]}\'',
        f'tumour_name = \'{config_settings["tumour_name"]}\'',
        f'normal_name = \'{config_settings["normal_name"]}\'',
        f'tumour_bam = \'{sample_data_local_paths["tumour_bam_fp"]}\'',
        f'normal_bam = \'{sample_data_local_paths["normal_bam_fp"]}\'',
        f'tumour_bam_index = \'{sample_data_local_paths["tumour_bam_index_fp"]}\'',
        f'normal_bam_index = \'{sample_data_local_paths["normal_bam_index_fp"]}\'',
        f'tumour_smlv_vcf = \'{sample_data_local_paths.get("tumour_smlv_vcf_fp", "NOFILE")}\'',
        f'tumour_sv_vcf = \'{sample_data_local_paths.get("tumour_sv_vcf_fp", "NOFILE")}\''
    ]

    config_params_output_lines = [
        '// Output',
        f'output_dir = \'{OUTPUT_LOCAL_DIR}\'',
        'publish_mode = \'symlink\'',
    ]

    config_params_options_lines = [
        '// Options',
        f'annotate_gridss_calls = {config_settings["annotate_gridss_calls"]}',
    ]

    config_params_reference_lines = [
        '// Reference data',
        '// Reference genome',
        f'ref_data_genome = \'{REFERENCE_LOCAL_DIR / "genome/umccrise_hg38/hg38.fa"}\'',
        '// AMBER, COBALT',
        f'ref_data_amber_loci = \'{REFERENCE_LOCAL_DIR / "Amber/38/GermlineHetPon.38.vcf.gz"}\'',
        f'ref_data_cobalt_gc_profile = \'{REFERENCE_LOCAL_DIR / "Cobalt/38/GC_profile.1000bp.38.cnp"}\'',
        '// GRIDSS',
        f'ref_data_gridss_blacklist = \'{REFERENCE_LOCAL_DIR / "GRIDSS/38/ENCFF356LFX.bed"}\'',
        f'ref_data_gridss_breakend_pon = \'{REFERENCE_LOCAL_DIR / "GRIDSS/38/gridss_pon_single_breakend.38.bed"}\'',
        f'ref_data_gridss_breakpoint_pon = \'{REFERENCE_LOCAL_DIR / "GRIDSS/38/gridss_pon_breakpoint.38.bedpe"}\'',
        '// Linx',
        f'ref_data_linx_fragile_sites = \'{REFERENCE_LOCAL_DIR / "Linx/38/fragile_sites_hmf.38.csv"}\'',
        f'ref_data_linx_line_elements = \'{REFERENCE_LOCAL_DIR / "Linx/38/line_elements.38.csv"}\'',
        f'ref_data_linx_rep_origins = \'{REFERENCE_LOCAL_DIR / "Linx/38/heli_rep_origins_empty.bed"}\'',
        f'ref_data_linx_gene_transcript_dir = \'{REFERENCE_LOCAL_DIR / "Ensembl-Data-Cache/38"}\'',
        '// Misc',
        f'ref_data_known_hotspots = \'{REFERENCE_LOCAL_DIR / "Sage/38/KnownHotspots.somatic.38.vcf.gz"}\'',
        f'ref_data_known_fusions = \'{REFERENCE_LOCAL_DIR / "Known-Fusions/38/known_fusions.38.bedpe"}\'',
        f'ref_data_known_fusion_data = \'{REFERENCE_LOCAL_DIR / "Known-Fusions/38/known_fusion_data.38.csv"}\'',
        f'ref_data_driver_gene_panel = \'{REFERENCE_LOCAL_DIR / "Gene-Panel/38/DriverGenePanel.38.tsv"}\'',
    ]

    config_params_misc_lines = [
        '// GRIDSS JAR',
        'gridss_jar = \'/opt/gridss/gridss-2.12.1-gridss-jar-with-dependencies.jar\'',
        f'gridss_jvmheap = \'{config_settings["gridss_jvmheap"]}g\'',
    ]

    config_params_lines = [
        *config_params_input_lines,
        *config_params_output_lines,
        *config_params_options_lines,
        *config_params_reference_lines,
        *config_params_misc_lines,
    ]
    return '\n'.join(f'  {line}' for line in config_params_lines)


def get_config_misc():
    return textwrap.dedent(f'''
        process.cpus = 4
        process.cache = 'lenient'

        // Fail task if any command returns non-zero exit code
        shell = ['/bin/bash', '-euo', 'pipefail']

        dag {{
          enabled = true
          file = '{NEXTFLOW_DIR}/reports/dag.svg'
        }}

        report {{
          enabled = true
          file = '{NEXTFLOW_DIR}/reports/report.html'
        }}

        timeline {{
          enabled = true
          file = '{NEXTFLOW_DIR}/reports/timeline.html'
        }}

        trace {{
          enabled = true
          file = '{NEXTFLOW_DIR}/reports/trace.txt'
        }}
    ''')


def upload_data_outputs(ignore_work_dir_symlinks=True):
    # Upload main outputs, using the --exclude flag with paths symlinking to an excluded directory
    # prevents upload so we must process directories individually to avoid uploading the work dir
    # here
    LOGGER.info('uploading main outputs')
    for dirpath in OUTPUT_LOCAL_DIR.iterdir():
        if dirpath == NEXTFLOW_DIR:
            continue
        s3_work_dir_subdirs = str(dirpath).replace(str(OUTPUT_LOCAL_DIR), '').lstrip('/')
        execute_command(f'aws s3 sync {dirpath} {OUTPUT_DIR}{s3_work_dir_subdirs}')
    # Upload the Nextflow directory, the --exclude here works since no file will be symlinked to
    # the work dir
    s3_work_dir_subdirs = str(NEXTFLOW_DIR).replace(str(OUTPUT_LOCAL_DIR), '').lstrip('/')
    command = f'aws s3 sync --exclude=\'*{WORK_DIR.name}/*\' {NEXTFLOW_DIR} {OUTPUT_DIR}{s3_work_dir_subdirs}'
    execute_command(command)
    # Finally upload the work dir, include symlinks only if requested
    LOGGER.info('uploading Nextflow work dir')
    s3_work_dir_subdirs = str(WORK_DIR).replace(str(OUTPUT_LOCAL_DIR), '').lstrip('/')
    if ignore_work_dir_symlinks:
        command = f'aws s3 sync --no-follow-symlinks {WORK_DIR} {OUTPUT_DIR}{s3_work_dir_subdirs}'
    else:
        command = f'aws s3 sync --follow-symlinks {WORK_DIR} {OUTPUT_DIR}{s3_work_dir_subdirs}'
    execute_command(command)


def handle_signal(signum, frame):
    LOGGER.critical(f'catching {signal.Signals(signum)._name_}, uploading files before exiting')
    upload_data_outputs(ignore_work_dir_symlinks=False)
    signal.signal(signum, signal.SIG_DFL)
    signal.raise_signal(signum)


if __name__ == '__main__':
    main()
