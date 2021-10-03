process ANNOTATE {
  publishDir "${params.output_dir}", pattern: 'gridss_annotate', mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(gridss_vcf)

  output:
  tuple val(meta), path('gridss_annotate/sv_vcf.annotated.vcf.gz'), emit: vcf
  path('gridss_annotate/')

  script:
  """
  gridss_annotate_vcf_repeatmasker \
    --jar "${params.gridss_jar}" \
    --output gridss_annotate/sv_vcf.annotated.vcf.gz \
	  --workingdir gridss_annotate/work/ \
	  --threads 4 \
    "${gridss_vcf}"
  """
}
