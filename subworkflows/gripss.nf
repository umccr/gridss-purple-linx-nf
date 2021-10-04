include { SOFT_FILTER } from '../modules/local/gripss_soft_filter'
include { HARD_FILTER } from '../modules/local/gripss_hard_filter'


workflow GRIPSS {
  take:
    // Format: [meta, vcf]
    ch_gridss_sv_vcf
    ref_data_genome_dir
    ref_data_genome_fn
    ref_data_gridss_breakend_pon
    ref_data_gridss_breakpoint_pon
    ref_data_known_fusions

  main:
    SOFT_FILTER(
      ch_gridss_sv_vcf,
      ref_data_genome_dir,
      ref_data_genome_fn,
      ref_data_gridss_breakend_pon,
      ref_data_gridss_breakpoint_pon,
      ref_data_known_fusions,
    )
    HARD_FILTER(
      // Exclude index from input
      // Format: [meta, vcf]
      SOFT_FILTER.out.map { it[0..1] }
    )

  emit:
    // Format: [meta, vcf, tbi]
    soft = SOFT_FILTER.out
    // Format: [meta, vcf, tbi]
    hard = HARD_FILTER.out
}
