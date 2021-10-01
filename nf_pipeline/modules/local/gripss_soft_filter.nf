process SOFT_FILTER {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}", saveAs: { filename -> "gripss/${filename}" }

  input:
  tuple val(meta), path(gridss_vcf)
  path(ref_data_genome_dir)
  val(ref_data_genome_fn)
  path(breakend_pon)
  path(breakpoint_pon)
  path(known_fusions)

  output:
  tuple val(meta), path('*soft_filtered.vcf.gz'), path('*soft_filtered.vcf.gz.tbi')

  script:
  """
  java \
    -Xms4G \
    -Xmx16G \
    -cp /opt/hmftools/gripss-1.11.jar \
    com.hartwig.hmftools.gripss.GripssApplicationKt \
      -tumor "${meta.tumour_name}" \
      -reference "${meta.normal_name}" \
      -ref_genome "${ref_data_genome_dir}/${ref_data_genome_fn}" \
      -breakend_pon "${breakend_pon}" \
      -breakpoint_pon "${breakpoint_pon}" \
      -breakpoint_hotspot "${known_fusions}" \
      -input_vcf "${gridss_vcf}" \
      -output_vcf "${meta.tumour_name}.gridss.somatic.soft_filtered.vcf.gz"
  """
}
