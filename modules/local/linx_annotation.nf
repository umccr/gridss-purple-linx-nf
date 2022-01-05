process ANNOTATION {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(purple)
  path(fragile_sites)
  path(line_elements)
  path(ensembl_data_dir)
  path(known_fusion_data)
  path(driver_gene_panel)

  output:
  tuple val(meta), path('linx_annotation/')

  script:
  """
  java \
    -Xmx${params.mem_linx} \
    -jar "${params.jar_linx}" \
      -sample "${meta.tumour_name}" \
      -ref_genome_version 38 \
      -sv_vcf "${purple}/${meta.tumour_name}.purple.sv.vcf.gz" \
      -purple_dir "${purple}" \
      -output_dir linx_annotation/ \
      -fragile_site_file "${fragile_sites}" \
      -line_element_file "${line_elements}" \
      -ensembl_data_dir "${ensembl_data_dir}" \
      -check_fusions \
      -known_fusion_file "${known_fusion_data}" \
      -check_drivers \
      -driver_gene_panel "${driver_gene_panel}"
  """

  stub:
  """
  mkdir linx_annotation/
  """
}
