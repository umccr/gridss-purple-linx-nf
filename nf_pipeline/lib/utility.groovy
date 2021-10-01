// Collect sample files into single channel as single list value from multiple channels while preserving order
def group_by_meta(channels) {
  group_flatten(channels.collect { ch -> ch.map { [it[0], it[1..-1]] }})
}

def group_by_meta_interleave(channels) {
  group_flatten(channels)
}

def group_flatten(channels) {
  Channel.empty()
    .concat(
      *channels,
    )
    .groupTuple()
    .map { it.flatten() }
}

// Check that a given VCF contains records
def has_records_vcf(vcf_fp) {
  def command = "bcftools view -H ${vcf_fp} | head | wc -l"
  (return_code, stdout, stderr) = execute_command(command)
  return stdout.toInteger() > 0
}

def execute_command(command) {
  def command_fq = ['/bin/bash', '-c', command]
  def stdout = new StringBuilder()
  def stderr = new StringBuilder()
  def process = command_fq.execute()
  process.waitForProcessOutput(stdout, stderr)
  return [process.exitValue(), stdout, stderr]
}
