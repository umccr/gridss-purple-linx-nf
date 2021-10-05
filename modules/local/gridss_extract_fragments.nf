process EXTRACT_FRAGMENTS {
  publishDir "${params.output_dir}", pattern: 'gridss_extract_fragments', mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(bam), path(bai), path(manta_vcf)

  output:
  tuple val(meta), path("gridss_extract_fragments/${bam.getSimpleName()}.targeted.bam"), emit: bam
  path('gridss_extract_fragments/')

  script:
  output_fp = "gridss_extract_fragments/${bam.getSimpleName()}.targeted.bam"
  """
  # Run
  gridss_extract_overlapping_fragments \
    --jar "${params.gridss_jar}" \
    --targetvcf "${manta_vcf}" \
    --workingdir gridss_extract_fragments/work/ \
    --output "${output_fp}" \
    --threads "${params.cpus}" \
    "${bam}"
  # This script can exit silently, check that we have some reads in the output file before proceeding
  if [[ "\$(samtools view "${output_fp}" | head | wc -l)" -eq 0 ]]; then
    exit 1;
  fi;
  """
}
