process VISUALISER {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}", saveAs: { dp -> 'linx/plots/' }

  input:
  tuple val(meta), path(linx)
  path(ensembl_data_dir)

  output:
  tuple val(meta), path('linx_visualiser/plot/')

  script:
  """
  java \
    -Xmx${params.mem_linx} \
    -cp "${params.jar_linx}" \
    com.hartwig.hmftools.linx.visualiser.SvVisualiser \
      -sample "${meta.tumor_name}" \
      -ref_genome_version 38 \
      -ensembl_data_dir "${ensembl_data_dir}" \
      -plot_out linx_visualiser/plot \
      -data_out linx_visualiser/data \
      -vis_file_dir "${linx}" \
      -circos "${params.path_circos}" \
      -threads "${params.cpus}"
  """

  stub:
  """
  mkdir linx_visualiser/
  """
}
