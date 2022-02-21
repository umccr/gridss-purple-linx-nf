include { ANNOTATION } from '../modules/local/linx_annotation'
include { VISUALISER } from '../modules/local/linx_visualiser'

include { group_by_meta } from '../lib/utility.groovy'


workflow LINX {
  take:
    // Format: [meta, purple]
    ch_purple_dir
    ref_data_linx_fragile_sites
    ref_data_linx_line_elements
    ref_data_linx_ensembl_data_dir
    ref_data_known_fusion_data
    ref_data_driver_gene_panel

  main:
    ANNOTATION(
      ch_purple_dir,
      ref_data_linx_fragile_sites,
      ref_data_linx_line_elements,
      ref_data_linx_ensembl_data_dir,
      ref_data_known_fusion_data,
      ref_data_driver_gene_panel,
    )
    VISUALISER(
      ANNOTATION.out,
      ref_data_linx_ensembl_data_dir,
    )

  ch_linx_out = group_by_meta([
    ANNOTATION.out,
    VISUALISER.out,
  ])

  emit:
    // Format: [meta, linx_annotation, linx_visualiser]
    ch_linx_out
}
