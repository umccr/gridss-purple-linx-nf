process ANNOTATION {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(purple)
  path(fragile_sites)
  path(line_elements)
  path(rep_origins)
  path(gene_transcript_dir)
  path(known_fusion_data)
  path(driver_gene_panel)

  output:
  tuple val(meta), path('linx/')

  script:
  """
  java \
    -jar /opt/hmftools/linx_v1.16.jar \
      -sample "${meta.tumour_name}" \
      -ref_genome_version 38 \
      -sv_vcf "${purple}/${meta.tumour_name}.purple.sv.vcf.gz" \
      -purple_dir "${purple}" \
      -output_dir linx/ \
      -fragile_site_file "${fragile_sites}" \
      -line_element_file "${line_elements}" \
      -replication_origins_file "${rep_origins}" \
      -gene_transcripts_dir "${gene_transcript_dir}" \
      -check_fusions \
      -known_fusion_file "${known_fusion_data}" \
      -check_drivers \
      -driver_gene_panel "${driver_gene_panel}"
  """
}
