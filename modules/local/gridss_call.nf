process CALL {
  input:
  tuple val(meta), path(tumour_bam), path(normal_bam), path(gridss_assembled)
  path(ref_data_genome_dir)
  val(ref_data_genome_fn)
  path(blacklist)

  output:
  tuple val(meta), path('gridss_call/sv_vcf.vcf.gz')

  script:
  output_dir = 'gridss_call/'

  """
  # Create shadow directory with file symlinks of GRIDSS output dir to prevent cache invalidation
  # NOTE: for reasons that elude me, NF doesn't always stage in the workingdir; remove if it is present
  mkdir -p "${output_dir}"
  lndir \$(readlink -f "${gridss_assembled}/") "${output_dir}/"
  if [[ -L "${gridss_assembled.name}" ]]; then
    rm "${gridss_assembled}"
  fi
  # Run
  gridss \
    --jvmheap "${params.mem_gridss}" \
    --jar "${params.jar_gridss}" \
    --steps call \
    --labels "${meta.normal_name},${meta.tumour_name}" \
    --reference "${ref_data_genome_dir}/${ref_data_genome_fn}" \
    --blacklist "${blacklist}" \
    --workingdir "${output_dir}/work/" \
    --assembly "${output_dir}/sv_assemblies.bam" \
    --output "${output_dir}/sv_vcf.vcf.gz" \
    --threads "${params.cpus}" \
    "${normal_bam}" \
    "${tumour_bam}"
  """

  stub:
  """
  mkdir -p gridss_call/
  cat <<EOF > gridss_call/sv_vcf.vcf.gz
  ##fileformat=VCFv4.1
  #CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO
  .	.	.	.	.	.	.
  EOF
  """
}
