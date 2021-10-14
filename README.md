&nbsp;
&nbsp;
&nbsp;
<p align="center">
🚧🚨 <em>Under development</em> 🚨🚧
</p>

# GRIDSS/PURPLE/Linx pipeline
A Nextflow pipeline for the GRIDSS/PURPLE/Linx (GPL) toolkit used to call and annotate structural variants. The GPL toolkit
is comprised of distinct but closely integrated pieces of software that together leverage both copy number alterations and
structural variants detected in short reads to improve calling accuracy and sensitivity.

This pipeline is currently targeted to bcbio outputs.

**For AWS users**: please see this [README.md](deployment/README.md) for AWS usage and other info.

## Table of contents
* [Installation](#installation)
* [Usage](#usage)
* [Outputs](#outputs)
* [Requirements](#requirements)
* [Reference data](#reference-data)
* [License](#license)

## Installation
The GPL toolkit contains many pieces of software with numerous dependencies. It is recommended using the pre-built Docker
image with the Nextflow pipeline to avoid a laborious installation process. If you cannot or do not want to use Docker,
please see the [Requirements](#requirements) section for further information.

These installation instructions assume you'll be using the pre-built Docker image with the Nextflow pipeline. Docker must be
installed prior to usage.
```bash
# Clone repo
git clone https://github.com/umccr/gridss-purple-linx-nf.git && cd gridss-purple-linx-nf/

# Create a Conda environment and install Nextflow if required
conda create -p $(pwd -P)/conda_env/ -y -c bioconda -c conda-forge nextflow
conda activate conda_env/

# Test that you're good to go
./main.nf -help
```

## Usage
First you'll need to obtain reference data as described [here](#reference-data). Then create a configuration file (for
an example see: [`nextflow.config`](nextflow.config)). To execute the pipeline:
```bash
./main.nf
```

## Outputs
### Directories
| Name                  | Contents                                  |
| ---                   | ---                                       |
| `nextflow/`           | Pipeline config, logs, and reports        |
| `amber/`              | B-allele frequency                        |
| `cobalt/`             | Tumour/normal read depth ratios           |
| `gridss_preprocess/`  | Pre-processed reads                       |
| `gridss_assemble/`    | SV assemblies                             |
| `gridss_call/`        | SV calls                                  |
| `gridss_annotate/`    | SV annotation (RepeatMasker) [*optional*] |
| `gripss/`             | Filtered SVs                              |
| `purple/`             | CNA calls, purity, ploidy                 |
| `linx_annotation/`    | Data for clustered and annotated SVs      |
| `linx_visualiser/`    | Plots for clustered and annotated SVs     |

### Useful files
| Name                                      | Description                               |
| ---                                       | ---                                       |
| `linx_visualiser/plot/*png`               | SV plots                                  |
| `purple/plot/*png`                        | Purity, ploidy, circos, etc plots         |
| `purple/<tumour_name>.<vcf_type>.vcf.gz`  | VCFs provided to and annotated by PURPLE  |
| `gripps/<prefix>.hard_filtered.vcf.gz`    | Hard SV filter                            |
| `gripps/<prefix>.soft_filtered.vcf.gz`    | Soft SV filter                            |
| `nextflow/nextflow_log.txt`               | Pipeline log file                         |
| `nextflow/nextflow.config`                | Pipeline configuration used in run        |
| `nextflow/reports/timeline.html`          | Stage execution durations as a timeline   |

## Requirements
> Software versions only indicate what is currently in use rather than  strict requirements
### Pipeline
Assumes the pipeline will be executed using the provided Docker image
* [Docker](https://www.docker.com/get-started) (v20.10.7)
* [Nextflow](https://www.nextflow.io/) (v21.04.0)

### GPL toolkit
* [AMBER](https://github.com/hartwigmedical/hmftools/blob/master/amber/) (v3.5)
* [COBALT](https://github.com/hartwigmedical/hmftools/blob/master/cobalt/) (v1.11)
* [GRIDSS](https://github.com/PapenfussLab/gridss) (v2.12.2)
* [GRIPSS](https://github.com/hartwigmedical/hmftools/blob/master/gripss/) (v1.11)
* [PURPLE](https://github.com/hartwigmedical/hmftools/blob/master/purple/) (v3.1)
* [Linx](https://github.com/hartwigmedical/hmftools/blob/master/linx/) (v1.16)

## Reference data
The GPL toolkit requires a number of reference files. These can be obtained from the HMF Nextcloud instance
[here](https://nextcloud.hartwigmedicalfoundation.nl/s/LTiKTd8XxBqwaiC?path=%2FHMFTools-Resources). Alternatively, I've
precompiled the required files on S3, located at `s3://umccr-refdata-dev/gpl-nf/`.

## License
Software and code in this repository are under [GNU General Public License
v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html) unless otherwise indicated.
