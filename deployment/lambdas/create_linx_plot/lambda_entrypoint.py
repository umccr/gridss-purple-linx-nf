#!/usr/bin/env python3
import collections
import datetime
import glob
import json
import logging
import shutil
import subprocess


import util


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)

OUTPUT_BUCKET = util.get_environment_variable('OUTPUT_BUCKET')
REFERENCE_DATA = util.get_environment_variable('REFERENCE_DATA')


def main(event, context):
    # Log invocation data
    LOGGER.info(f'event: {json.dumps(event)}')
    LOGGER.info(f'context: {json.dumps(util.get_context_info(context))}')

    # Check inputs and ensure that output directory is writable
    if response_error := validate_event_data(event):
        return response_error

    # Download data
    linx_annotations_dir = download_linx_annotation_data(event['gpl_directory'])
    ensembl_data_cache_dir = download_ensembl_data_cache()

    # Grab some information about requested plot for selected genes
    if 'gene_ids' in event:
        gene_data = get_gene_data(f'{ensembl_data_cache_dir}ensembl_gene_data.csv')
        check_gene_symbol(cluster_genes, gene_data, event)

    # Generate LINX plot
    plot_dir = generate_plots(linx_annotations_dir, ensembl_data_cache_dir, event)

    # Upload plots
    s3_linx_manual_path = f's3://{OUTPUT_BUCKET}/{event["gpl_directory"]}/linx/plots_manual/'
    command = f'aws s3 sync {plot_dir} {s3_linx_manual_path}'
    execute_command(command)


def check_gene_symbol(gene_data, event):
    genes = event['gene_ids'].split(';')
    genes_missing = list()
    for gene in genes:
        if gene in gene_data:
            continue
        genes_missing.append(gene)
    if genes_missing:
        genes_missing_str = '\n\t'.join(genes_missing)
        plurality = 'genes' if len(genes_missing) > 1 else 'gene'
        msg = f'{len(genes_missing)} {plurality} not present in the Ensembl data cache:\n\t{genes_missing_str}'
        raise ValueError(msg)


def validate_event_data(event):
    args_known = [
        'sample_id',
        'cluster_ids',
        'regions',
        'chromosomes',
        'gene_ids',
        'gpl_directory',
    ]
    args_unknown = [arg for arg in event if arg not in args_known]
    if args_unknown:
        plurality = 'arguments' if len(args_unknown) > 1 else 'argument'
        args_unknown_str = '\n\t'.join(args_unknown)
        msg = f'got {len(args_unknown)} unknown arguments:\n\t{args_unknown_str}'
        raise ValueError(msg)

    if not event.get('sample_id'):
        raise ValueError('The required argument sample_id is missing')
    if not event.get('gpl_directory'):
        raise ValueError('The required argument gpl_directory is missing')

    has_cluster_ids = 'cluster_ids' in event
    has_chromosomes = 'chromosomes' in event
    has_gene_ids = 'gene_ids' in event
    has_regions = 'regions' in event
    if has_cluster_ids and has_chromosomes:
        raise ValueError('Got mutually exclusive arguments cluster_ids and chromosomes')
    if has_regions and has_chromosomes:
        raise ValueError('Got mutually exclusive arguments regions and chromosomes')
    if not (has_cluster_ids or has_chromosomes or has_gene_ids):
        raise ValueError('Either cluster_ids, chromosomes, or gene_ids is required')

    # Disallow trailing ';'
    if has_gene_ids and event['gene_ids'].endswith(';'):
        raise ValueError('the \'gene_ids\' option cannot end with a \';\'')
    if has_regions:
        # Disallow trailing ';'
        if event['regions'].endswith(';'):
            raise ValueError('the \'regions\' option cannot end with a \';\'')
        # Check region tokens match expected format
        region_regex = re.compile(r'^(chr[0-9]):([0-9]+):([0-9]+)$')
        chrms_region = set()
        for region in event['regions'].split(';'):
            if not (re_result := region_regex.match(region)):
                raise ValueError(f'could not apply regex \'{region_regex}\' to \'{region}\'')
            chrms_region.append(re_result.group(1))
        # Ensure that provided contigs/chromosomes are in the expected format
        chrm_invalid = validate_chromosomes(chrms_region)
        if chrm_invalid:
            chrm_invalid_string = ', '.join(chrm_invalid)
            plurality = 'chromosomes' if len(chrm_invalid) > 1 else 'chromosome'
            msg = f'Got unexpected {plurality} for the \'regions\' option: {chrm_invalid_string}'
            raise ValueError(msg)

    if has_chromosomes:
        chrm_invalid = validate_chromosomes(event['chromosomes'].split(','))
        if chrm_invalid:
            chrm_invalid_string = ', '.join(chrm_invalid)
            plurality = 'chromosomes' if len(chrm_invalid) > 1 else 'chromosome'
            msg = f'Got unexpected {plurality} for the \'chromosomes\' option: {chrm_invalid_string}'
            raise ValueError(msg)
    event['gpl_directory'] = event['gpl_directory'].rstrip('/')


def validate_chromosomes(chromosomes):
    chrm_valid = {
        *{f'chr{i}' for i in range(1, 23)},
        'chrX',
        'chrY',
    }
    chrm_invalid = list()
    for chrm in event['chromosomes'].split(','):
        if chrm not in chrm_valid:
            chrm_invalid.append(chrm)
    return chrm_invalid


def download_linx_annotation_data(gpl_directory):
    s3_path = f's3://{OUTPUT_BUCKET}/{gpl_directory}/linx/annotations/'
    local_path = '/tmp/linx_annotations/'
    execute_command(f'aws s3 sync {s3_path} {local_path}/')
    return local_path


def download_ensembl_data_cache():
    s3_path = f'{REFERENCE_DATA}Ensembl-Data-Cache/38/'
    local_path = '/tmp/ensembl-data-cache/'
    execute_command(f'aws s3 sync {s3_path} {local_path}')
    return local_path


def get_gene_data(fp):
    gene_data = dict()
    with open(fp, 'r') as fh:
        line_token_gen = (line.rstrip().split(',') for line in fh)
        header_tokens = next(line_token_gen)
        RecordGene = collections.namedtuple('RecordGene', header_tokens)
        for line_tokens in line_token_gen:
            record = RecordGene(*line_tokens)
            assert record.GeneName not in gene_data
            gene_data[record.GeneName] = record
    return gene_data


def generate_plots(linx_annotations_dir, ensembl_data_cache_dir, event):
    # Configurate options
    plot_options_list = list()
    if 'chromosomes' in event:
        plot_options_list.append(f'-chromosome {event["chromosomes"]}')
    if 'cluster_ids' in event:
        plot_options_list.append(f'-clusterId {event["cluster_ids"]}')
    if 'gene_ids' in event:
        plot_options_list.append(f'-gene \"{event["gene_ids"]}\"')
        plot_options_list.append(f'-restrict_cluster_by_gene')
    if 'regions' in event:
        plot_options_list.append(f'-specific_regions \"{event["regions"]}\"')
    plot_options = ' '.join(plot_options_list)
    # Set outputs
    output_base_dir = '/tmp/linx/'
    output_plot_dir = f'{output_base_dir}plot/'
    output_data_dir = f'{output_base_dir}data/'
    # Construct full command
    command = (f'''
      java \
        -cp /opt/hmftools/linx.jar \
        com.hartwig.hmftools.linx.visualiser.SvVisualiser \
          -sample {event["sample_id"]} \
          -ensembl_data_dir {ensembl_data_cache_dir} \
          -vis_file_dir {linx_annotations_dir} \
          -plot_out {output_plot_dir} \
          -data_out {output_data_dir} \
          -circos circos \
          -ref_genome_version 38 \
          {plot_options}
    ''')
    execute_command(command)
    # Rename plots to include datetime stamp
    dts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    for fp_src in glob.glob(f'{output_plot_dir}*.png'):
        fp_dst = fp_src.replace('.png', f'__{dts}.png')
        shutil.move(fp_src, fp_dst)
    return output_plot_dir


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
        msg_hline = f'Non-zero return code for command: {result.args}'
        LOGGER.critical(msg_hline)
        LOGGER.critical(f'stdout: {result.stdout}')
        LOGGER.critical(f'stderr: {result.stderr}')
        raise ValueError(msg_hline)
    return result
