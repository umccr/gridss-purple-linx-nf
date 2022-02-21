include { GRIDSS } from '../subworkflows/gridss'
include { LINX } from '../subworkflows/linx'

include { AMBER } from '../modules/local/amber'
include { COBALT } from '../modules/local/cobalt'
include { GRIPSS } from '../modules/local/gripss'
include { PURPLE } from '../modules/local/purple'
include { REPORT } from '../modules/local/report'

include { group_by_meta } from '../lib/utility.groovy'
include { group_by_meta_interleave } from '../lib/utility.groovy'
include { has_records_vcf } from '../lib/utility.groovy'


// Some notes:

// BAM indexes are required for AMBER, COBALT, and GRIDSS extract fragments. Both AMBER and COBALT are able to locate BAM
// indexes by resolving symlinks but GRIDSS extract fragments cannot. So we explicitly provided indexes for each of these
// processes for consistency.

// Annotations provided by RepeatMasker in GRIDSS_ANNOTATE aren't strictly required by GRIPSS as
// stated in the documentation. Instead they are needed for certain functionality in the downstream
// tool, Linx. See: https://github.com/hartwigmedical/hmftools/issues/170.

// We are operating on channels as if multiple samples had been provided despite there only a single sample. This is done as
// we may in the future expand execution to involve more than one sample.


// Pre-flight to be done here


// Input sample data
meta = [
 'tumor_name': params.tumor_name,
 'normal_name': params.normal_name,
]
ch_meta = Channel.value(meta)
ch_input_bams_tumor_and_index = Channel.of([
  meta,
  file(params.tumor_bam),
  file(params.tumor_bam_index),
])
ch_input_bams_normal_and_index = Channel.of([
  meta,
  file(params.normal_bam),
  file(params.normal_bam_index),
])
ch_input_smlv_vcfs = Channel.of([
  meta,
  file(params.tumor_smlv_vcf),
])
ch_input_sv_vcfs = Channel.of([
  meta,
  file(params.tumor_sv_vcf),
])


// Reference data
// Reference genome
ref_data_genome_dir = file(params.ref_data_genome).parent
ref_data_genome_fn = file(params.ref_data_genome).name
// AMBER, COBALT
ref_data_amber_loci = file(params.ref_data_amber_loci)
ref_data_cobalt_gc_profile = file(params.ref_data_cobalt_gc_profile)
// GRIDSS
ref_data_gridss_blacklist = file(params.ref_data_gridss_blacklist)
ref_data_gridss_breakend_pon = file(params.ref_data_gridss_breakend_pon)
ref_data_gridss_breakpoint_pon = file(params.ref_data_gridss_breakpoint_pon)
// Linx
ref_data_linx_fragile_sites = file(params.ref_data_linx_fragile_sites)
ref_data_linx_line_elements = file(params.ref_data_linx_line_elements)
// Misc
ref_data_ensembl_data_dir = file(params.ref_data_ensembl_data_dir)
ref_data_known_hotspots = file(params.ref_data_known_hotspots)
ref_data_known_fusions = file(params.ref_data_known_fusions)
ref_data_known_fusion_data = file(params.ref_data_known_fusion_data)
ref_data_driver_gene_panel = file(params.ref_data_driver_gene_panel)


workflow GPL {
  // Create interleaved BAM + index channel for AMBER and COBALT
  // Format: [meta, tumor_bam, normal_bam, tumor_bam_index, normal_bam_index]
  ch_input_bams = group_by_meta_interleave([
    ch_input_bams_tumor_and_index,
    ch_input_bams_normal_and_index,
  ])
  AMBER(ch_input_bams, ref_data_amber_loci)
  COBALT(ch_input_bams, ref_data_cobalt_gc_profile)
  GRIDSS(
    ch_input_bams_tumor_and_index,
    // Format: [meta, bam]
    ch_input_bams_normal_and_index.map { it[0..1] },
    ch_input_sv_vcfs,
    ref_data_genome_dir,
    ref_data_genome_fn,
    ref_data_gridss_blacklist,
  )
  GRIPSS(
    // Format: [meta, vcf]
    GRIDSS.out,
    ref_data_genome_dir,
    ref_data_genome_fn,
    ref_data_gridss_breakend_pon,
    ref_data_gridss_breakpoint_pon,
    ref_data_known_fusions,
  )

  // Filter samples that have no variants by exploiting '.join'. Any sample absent from
  // 'ch_sample_has_filtered_svs' will be excluded below
  // Format: [meta]
  ch_sample_has_filtered_svs = GRIPSS.out.hard.filter { meta, vcf_fp, vcf_index_fp ->
      return has_records_vcf(vcf_fp)
    }
    .map { it[0] }
  // Format: [meta, amber, cobalt, gripss_soft_bam, gripss_soft_bai, gripss_hard_bam, gripss_hard_bai, tumor_smvl_vcf]
  ch_purple_input_all = group_by_meta([
    AMBER.out,
    COBALT.out,
    GRIPSS.out.soft,
    GRIPSS.out.hard,
    ch_input_smlv_vcfs,
  ])
  // Format: [meta, amber, cobalt, gripss_soft_bam, gripss_soft_bai, gripss_hard_bam, gripss_hard_bai, tumor_smvl_vcf]
  ch_purple_input = ch_purple_input_all
    .join(ch_sample_has_filtered_svs)
  PURPLE(
    ch_purple_input,
    ref_data_genome_dir,
    ref_data_genome_fn,
    ref_data_cobalt_gc_profile,
    ref_data_known_hotspots,
    ref_data_driver_gene_panel,
  )

  // Check that PURPLE created SV VCFs and that these contain at least one record
  // Format: [meta, purple]
  ch_linx_input = PURPLE.out.filter { meta, purple_dir ->
      def vcf_fp = "${purple_dir}/${meta.tumor_name}.purple.sv.vcf.gz"
      return has_records_vcf(vcf_fp)
    }
  LINX(
    ch_linx_input,
    ref_data_linx_fragile_sites,
    ref_data_linx_line_elements,
    ref_data_ensembl_data_dir,
    ref_data_known_fusion_data,
    ref_data_driver_gene_panel,
  )

  // Generate a Rmd report for Linx output
  REPORT(
    // Format: [meta, linx_annotation, linx_visualiser]
    LINX.out,
  )
}
