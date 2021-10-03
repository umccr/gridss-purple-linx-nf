#!/usr/bin/env nextflow
nextflow.enable.dsl = 2

include { GPL } from './workflows/gridss_purple_linx'

workflow {
  GPL()
}
