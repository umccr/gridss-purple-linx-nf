process GRIPSS {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}", saveAs: { fp -> "gripss/${fp}" }

  memory params.mem_gripss

  input:
  tuple val(meta), path(gridss_vcf)
  path(ref_data_genome_dir)
  val(ref_data_genome_fn)
  path(breakend_pon)
  path(breakpoint_pon)
  path(known_fusions)

  output:
  tuple val(meta), path('*.gripss.filtered.vcf.gz'), path('*.gripss.filtered.vcf.gz.tbi'), emit: hard
  tuple val(meta), path('*.gripss.vcf.gz'), path('*.gripss.vcf.gz.tbi'), emit: soft

  script:
  """
  java \
    -Xmx${params.mem_gripss} \
    -jar "${params.jar_gripss}" \
    -sample "${meta.tumor_name}" \
    -reference "${meta.normal_name}" \
    -ref_genome "${ref_data_genome_dir}/${ref_data_genome_fn}" \
    -pon_sgl_file "${breakend_pon}" \
    -pon_sv_file "${breakpoint_pon}" \
    -known_hotspot_file "${known_fusions}" \
    -vcf "${gridss_vcf}" \
    -output_dir ./
  """

  stub:
  """
  cat <<EOF > ${meta.tumor_name}.gripss.filtered.vcf.gz
  ##fileformat=VCFv4.1
  #CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO
  .	.	.	.	.	.	.
  EOF
  touch ${meta.tumor_name}.gripss.filtered.vcf.gz.tbi
  touch ${meta.tumor_name}.gripss.vcf.gz
  touch ${meta.tumor_name}.gripss.vcf.gz.tbi
  """
}
