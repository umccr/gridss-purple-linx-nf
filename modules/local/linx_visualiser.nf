process VISUALISER {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(linx)
  path(gene_transcript_dir)

  output:
  tuple val(meta), path('linx_visualiser/')

  script:
  """
  java \
    -cp /opt/hmftools/linx_v1.16.jar \
    com.hartwig.hmftools.linx.visualiser.SvVisualiser \
      -sample "${meta.tumour_name}" \
      -gene_transcripts_dir "${gene_transcript_dir}" \
      -plot_out linx_visualiser/plot \
      -data_out linx_visualiser/data \
      -vis_file_dir "${linx}" \
      -circos /opt/circos/bin/circos \
      -threads "${params.cpus}"
  """
}
