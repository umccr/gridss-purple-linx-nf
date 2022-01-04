process HARD_FILTER {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}", saveAs: { filename -> "gripss/${filename}" }

  input:
  tuple val(meta), path(gripss_soft_filter_vcf)

  output:
  tuple val(meta), path('*hard_filtered.vcf.gz'), path('*hard_filtered.vcf.gz.tbi')

  script:
  """
  java \
    -Xms4G \
    -Xmx${params.mem_gripss} \
    -cp "${params.jar_gripss}" \
    com.hartwig.hmftools.gripss.GripssHardFilterApplicationKt \
      -input_vcf "${gripss_soft_filter_vcf}" \
      -output_vcf "${meta.tumour_name}.gridss.somatic.hard_filtered.vcf.gz"
  """
}
