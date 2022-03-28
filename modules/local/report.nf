process REPORT {
  publishDir "${params.output_dir}", mode: "${params.publish_mode}"

  input:
  tuple val(meta), path(linx_annotation), path(linx_visualiser)

  output:
  path('*_linx.html')

  script:
  """
  gpgr.R linx \
    --sample ${meta.tumor_name} \
    --plot ${linx_visualiser}/ \
    --table ${linx_annotation}/ \
    --out ${meta.tumor_name}_linx.html;
  """

  stub:
  """
  touch ${meta.tumor_name}_linx.html
  """
}
