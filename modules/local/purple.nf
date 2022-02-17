// If provided, we must first filter small variant VCF records missing allelic depth (AD) as this field is required by
// PURPLE. Records have no AD in cases where only strelka2 and not vardict calls are available - strelka2 does not always
// generate AD for records. This will be addressed once we migrate to DRAGEN.


process PURPLE {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(amber), path(cobalt), path(sv_soft_vcf), path(sv_soft_vcf_index), path(sv_hard_vcf), path(sv_hard_vcf_index), path(smlv_tumor_vcf)
  path(ref_data_genome_dir)
  val(ref_data_genome_fn)
  path(gc_profile)
  path(known_hotspots)
  path(driver_gene_panel)

  output:
  tuple val(meta), path('purple/')

  script:
  """
  # If we have the tumor small variant VCF then filter records missing AD and set argument value
  if [[ "${smlv_tumor_vcf.name}" != 'NOFILE' ]]; then
    bcftools filter -Oz -e 'FORMAT/AD[*]="."' "${smlv_tumor_vcf}" > tumor_small_variants_filtered.vcf.gz
    smlv_tumor_vcf_arg='-somatic_vcf tumor_small_variants_filtered.vcf.gz'
  else
    smlv_tumor_vcf_arg=''
  fi
  # Run PURPLE
  java \
    -Xmx${params.mem_purple} \
    -jar "${params.jar_purple}" \
      -reference "${meta.normal_name}" \
      -tumor "${meta.tumor_name}" \
      -sv_recovery_vcf "${sv_soft_vcf}" \
      -structural_vcf "${sv_hard_vcf}" \
      \${smlv_tumor_vcf_arg} \
      -amber "${amber}" \
      -cobalt "${cobalt}" \
      -output_dir purple/ \
      -gc_profile "${gc_profile}" \
      -driver_catalog \
      -driver_gene_panel "${driver_gene_panel}" \
      -somatic_hotspots "${known_hotspots}" \
      -ref_genome "${ref_data_genome_dir}/${ref_data_genome_fn}" \
      -threads "${params.cpus}" \
      -circos "${params.path_circos}"
  # PURPLE can fail silently, check that at least the PURPLE SV VCF is created
  if [[ ! -s "purple/${meta.tumor_name}.purple.sv.vcf.gz" ]]; then
    exit 1;
  fi
  """

  stub:
  """
  mkdir purple/
  cat <<EOF > purple/${meta.tumor_name}.purple.sv.vcf.gz
  ##fileformat=VCFv4.1
  #CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO
  .	.	.	.	.	.	.
  EOF
  """
}
