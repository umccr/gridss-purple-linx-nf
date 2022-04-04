process EXTRACT_FRAGMENTS {
  memory params.mem_gridss

  input:
  tuple val(meta), path(bam), path(bai), path(manta_vcf)

  output:
  tuple val(meta), path("gridss_extract_fragments/${bam.getSimpleName()}.targeted.bam")

  script:
  output_fp = "gridss_extract_fragments/${bam.getSimpleName()}.targeted.bam"
  """
  # Run
  gridss_extract_overlapping_fragments \
    --jar "${params.jar_gridss}" \
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

  stub:
  """
  mkdir -p gridss_extract_fragments/
  touch gridss_extract_fragments/${bam.getSimpleName()}.targeted.bam
  """
}
