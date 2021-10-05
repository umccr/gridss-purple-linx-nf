process COBALT {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(tumour_bam), path(normal_bam), path(tumour_bai), path(normal_bai)
  path(gc_profile)

  output:
  tuple val(meta), path('cobalt/')

  script:
  """
  java \
    -Xmx8G \
    -cp /opt/hmftools/cobalt-1.11.jar \
    com.hartwig.hmftools.cobalt.CountBamLinesApplication \
      -tumor "${meta.tumour_name}" \
      -tumor_bam "${tumour_bam}" \
      -reference "${meta.normal_name}" \
      -reference_bam "${normal_bam}" \
      -output_dir cobalt/ \
      -threads "${params.cpus}" \
      -gc_profile "${gc_profile}"
  """
}
