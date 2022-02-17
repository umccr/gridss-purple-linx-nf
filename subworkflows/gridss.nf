include { ANNOTATE } from '../modules/local/gridss_annotate'
include { ASSEMBLE } from '../modules/local/gridss_assemble'
include { CALL } from '../modules/local/gridss_call'
include { EXTRACT_FRAGMENTS } from '../modules/local/gridss_extract_fragments'
include { PREPROCESS } from '../modules/local/gridss_preprocess'

include { group_by_meta } from '../lib/utility.groovy'
include { has_records_vcf } from '../lib/utility.groovy'


workflow GRIDSS {
  take:
    // Format: [meta, bam, bai]
    ch_bams_tumour_and_index
    // Format: [meta, bam]
    ch_bams_normal
    // Format: [meta, vcf]
    ch_sv_vcfs
    ref_data_genome_dir
    ref_data_genome_fn
    ref_data_gridss_blacklist

  main:
    // Create channels to sort inputs for fragment extraction
    // Format: [meta, bam]
    ch_bams_tumour_preextract = ch_bams_tumour_and_index.map { it[0..1] }
    // Format: [meta]
    ch_sample_has_sv_vcfs = ch_sv_vcfs
      .branch { meta, vcf_fp ->
        yes: vcf_fp.name != 'NOFILE'
          return meta
        no: vcf_fp.name == 'NOFILE'
          return meta
      }
    // Select samples with a tumour SV VCF and run GRIDSS fragment extraction
    // Format: [meta, bam, bai, vcf]
    ch_gridss_extract_fragments_input_all = group_by_meta([
      ch_bams_tumour_and_index,
      ch_sv_vcfs,
    ])
    // Format: [meta, bam, bai, vcf]
    ch_gridss_extract_fragments_input = ch_gridss_extract_fragments_input_all
      .join(ch_sample_has_sv_vcfs.yes)
    EXTRACT_FRAGMENTS(
        ch_gridss_extract_fragments_input,
    )
    // Join extracted fragment BAMs with input BAMs (that had no tumour SV VCF)
    // Format: [meta, bam]
    ch_bams_tumour_no_sv_vcfs = ch_bams_tumour_preextract
        .join(ch_sample_has_sv_vcfs.no)
    // Format: [meta, bam]
    ch_bams_tumour = Channel.empty()
      .concat(
        ch_bams_tumour_no_sv_vcfs,
        EXTRACT_FRAGMENTS.out,
      )

    // Format: [meta, tumour_bam, normal_bam]
    ch_gridss_preprocess_input = group_by_meta([
      ch_bams_tumour,
      ch_bams_normal,
    ])
    PREPROCESS(
      ch_gridss_preprocess_input,
      ref_data_genome_dir,
      ref_data_genome_fn,
    )

    // Format: [meta, tumour_bam, normal_bam, preprocess]
    ch_gridss_assemble_input = group_by_meta([
      ch_bams_tumour,
      ch_bams_normal,
      PREPROCESS.out,
    ])
    ASSEMBLE(
      ch_gridss_assemble_input,
      ref_data_genome_dir,
      ref_data_genome_fn,
      ref_data_gridss_blacklist,
    )

    // Format: [meta, tumour_bam, normal_bam, assemble]
    ch_gridss_call_input = group_by_meta([
      ch_bams_tumour,
      ch_bams_normal,
      ASSEMBLE.out,
    ])
    CALL(
      ch_gridss_call_input,
      ref_data_genome_dir,
      ref_data_genome_fn,
      ref_data_gridss_blacklist,
    )

    // Filter any GRIDSS VCFs that have no records
    // Format: [meta, vcf]
    ch_gridss_svs = CALL.out.filter { meta, vcf_fp ->
        return has_records_vcf(vcf_fp)
      }

    // Annotate with RepeatMasker, required for Linx
    // Format: [meta, vcf]
    ANNOTATE(ch_gridss_svs)

  emit:
    // Format: [meta, vcf]
    ANNOTATE.out.vcf
}
