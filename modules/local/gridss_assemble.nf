process ASSEMBLE {
  publishDir "${params.output_dir}", pattern: 'gridss_assemble', mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(tumour_bam), path(normal_bam), val(gridss_preprocessed)

  path(ref_data_genome_dir)
  val(ref_data_genome_fn)
  path(blacklist)

  output:
  tuple val(meta), path('gridss_assemble/')

  script:
  output_dir = 'gridss_assemble/'

  """
  # Create shadow directory with file symlinks of GRIDSS 'workingdir' to prevent cache invalidation
  # NOTE: for reasons that elude me, NF doesn't always stage in the workingdir; remove if it is present
  mkdir -p "${output_dir}/work/"
  lndir \$(readlink -f "${gridss_preprocessed}/") "${output_dir}/work"
  if [[ -L "${gridss_preprocessed.name}" ]]; then
    rm "${gridss_preprocessed}"
  fi
  # Run
  gridss \
    --jvmheap "${params.mem_gridss}" \
    --jar "${params.jar_gridss}" \
    --steps assemble \
    --labels "${meta.normal_name},${meta.tumour_name}" \
    --reference "${ref_data_genome_dir}/${ref_data_genome_fn}" \
    --blacklist "${blacklist}" \
    --workingdir "${output_dir}/work" \
    --assembly "${output_dir}/sv_assemblies.bam" \
    --threads "${params.cpus}" \
    "${normal_bam}" \
    "${tumour_bam}"
  """
}
