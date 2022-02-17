process AMBER {
  input:
  tuple val(meta), path(tumor_bam), path(normal_bam), path(tumor_bai), path(normal_bai)
  path(loci)

  output:
  tuple val(meta), path('amber/')

  script:
  """
  java \
    -Xmx${params.mem_amber} \
    -cp "${params.jar_amber}" \
    com.hartwig.hmftools.amber.AmberApplication \
      -tumor "${meta.tumor_name}" \
      -tumor_bam "${tumor_bam}" \
      -reference "${meta.normal_name}" \
      -reference_bam "${normal_bam}" \
      -output_dir amber/ \
      -threads "${params.cpus}" \
      -loci "${loci}"
  """

  stub:
  """
  mkdir -p amber/
  """
}
