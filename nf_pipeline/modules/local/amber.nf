process AMBER {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(tumour_bam), path(normal_bam), path(tumour_bai), path(normal_bai)
  path(loci)

  output:
  tuple val(meta), path('amber/')

  script:
  """
  java \
    -Xmx16G \
    -cp /opt/hmftools/amber-3.5.jar \
    com.hartwig.hmftools.amber.AmberApplication \
      -tumor "${meta.tumour_name}" \
      -tumor_bam "${tumour_bam}" \
      -reference "${meta.normal_name}" \
      -reference_bam "${normal_bam}" \
      -output_dir amber/ \
      -threads 4 \
      -loci "${loci}"
  """
}
