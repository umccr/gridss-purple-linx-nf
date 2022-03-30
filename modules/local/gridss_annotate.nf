process ANNOTATE {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}", saveAs: { fp -> "gridss/${file(fp).getName()}" }

  memory params.mem_gridss

  input:
  tuple val(meta), path(gridss_vcf)

  output:
  tuple val(meta), path('gridss_annotate/sv_vcf.annotated.vcf.gz'), emit: vcf
  path('gridss_annotate/sv_vcf.annotated*')

  script:
  """
  gridss_annotate_vcf_repeatmasker \
    --jar "${params.jar_gridss}" \
    --output gridss_annotate/sv_vcf.annotated.vcf.gz \
    --workingdir gridss_annotate/work/ \
    --threads "${params.cpus}" \
    "${gridss_vcf}"
  """

  stub:
  """
  mkdir -p gridss_annotate/
  touch gridss_annotate/sv_vcf.annotated.vcf.gz
  """
}
