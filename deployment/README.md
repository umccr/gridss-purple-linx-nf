# GRIDSS/PURPLE/LINX pipeline stack

The AWS stack for running the GRIDSS/PURPLE/LINX (GPL) pipeline. Job orchestration and pipeline execution is handled by
Batch. Specifically, jobs are run on Batch-provisioned EC2 instances using a Docker container that includes the GPL pipeline,
a Python wrapper script, and all required dependencies. The wrapper [Python script](assets/run_gpl.py) pulls reference and
sample data, creates a configuration file, runs the GPL pipeline, and finally uploads results to S3.

The GPL pipeline runs entirely within a single EC2 instance rather than creating individual Batch jobs for each NF task and
sending them to multiple instances. This avoids having to pull reference data for each job, which can take up to 30 minutes.
This approach will continue to be the most suitable solution until Nextflow can utilise a shared filesystem between jobs
without using enterprise plugins.

## Table of contents

* [Schematic](#schematic)
* [Prerequisites](#prerequisites)
* [Deployment](#deployment)
* [Usage](#usage)

## Schematic

<p align="center"><img src="images/schematic.png" width="80%"></p>

## Prerequisites

It is assumed that the necessary VPC, security groups, and S3 buckets are appropriately deployed and configured in the target
AWS account.

## Deployment

The stack has some software requirements for deploy:

* AWS CDK Toolkit (available through Homebrew or npm)
* Docker
* Python3

### Create virtual environment

```bash
python3 -m venv .venv/
pip install -r requirements.txt
```

### Build Docker image

>It is assumed that an ECR repository named `gpl-nf` has been manually created. For cross-account access of the Docker
>image (i.e. prod pulling from dev), you must set a IAM policy containing a permission statement such as:

```JSON
{
  "Version": "2008-10-17",
  "Statement": [
    {
      "Sid": "new statement",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::472057503814:root"
      },
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:BatchGetImage",
        "ecr:DescribeImages",
        "ecr:DescribeRepositories",
        "ecr:GetDownloadUrlForLayer",
        "ecr:GetRepositoryPolicy",
        "ecr:ListImages"
      ]
    }
  ]
}
```

Build and upload Docker image

```bash
VERSION=0.1.13
AWS_PROVIDER_URL=843407916570.dkr.ecr.ap-southeast-2.amazonaws.com
# Build
docker build -t ${AWS_PROVIDER_URL}/gpl-nf:${VERSION} -f docker/Dockerfile .
# Upload
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin "${AWS_PROVIDER_URL}"
docker push ${AWS_PROVIDER_URL}/gpl-nf:${VERSION}
```

### Build Lambda layers

```bash
for dir in $(find $(pwd -P)/lambdas/layers/ -maxdepth 1 -mindepth 1 -type d); do
  rm -r ${dir}/build/;
  docker run --rm -v ${dir}:/local/ -w /local/ public.ecr.aws/sam/build-python3.8 \
    pip install -r requirements.txt -t ./build/package/python/;
  (cd ${dir}/build/package/; zip ../python38-${dir##*/}.zip $(find . -type f ! -path '*__pycache__*'));
done
```

### Deploy stack

Set appropriate environment with `-c environment=<dev|prod>`

```bash
cdk deploy -c environment=dev
```

## Usage

### Automatic submission with identifiers

A GPL job can be launched with either a subject identifier (e.g. `SBJ00001`) or both a tumor sample identifier and
normal sample identifier (e.g. `PRJ000001`) using the `gpl_submit_job` Lambda function. This Lambda function queries the
[data portal API](https://github.com/umccr/data-portal-apis) to automatically collect the necessary input data, which is
then passed the the `gpl_submit_job_manual` Lambda function to launch the Batch job.

When a subject has multiple tumor/normal samples, the Lambda function will refuse to run if provided a subject
identifier and instead will require the user to explicitly provide the desired tumor sample identifier and normal
sample identifier.

```bash
# Subject identifier
aws lambda invoke \
  --function-name gpl_submit_job \
  --cli-binary-format raw-in-base64-out \
  --payload '{"subject_id": "SBJ00001"}' \
  response.json

# Sample identifiers
aws lambda invoke \
  --function-name gpl_submit_job \
  --cli-binary-format raw-in-base64-out \
  --payload '{"tumor_sample_id": "PRJ000001", "normal_sample_id": "PRJ000002"}' \
  response.json
```

#### Lambda arguments

| Argument              | Description               |
| ---                   | ---                       |
| `subject_id`          | Subject identifier        |
| `tumor_sample_id`     | Tumor sample identifier   |
| `normal_sample_id`    | Normal sample identifier  |
> Either `subject_id` or both `tumor_sample_id` and `normal_sample_id` are required. Subject and sample
> identifiers are mutually exclusive.

### Manual submission with filepaths

For cases where additional control is needed over the inputs and configuration, a manual job submission Lambda function
is available. This is useful for running samples that are not in the data portal or adjusting Nextflow pipeline
parameters.

```bash
aws lambda invoke \
  --function-name gpl_submit_job_manual \
  --cli-binary-format raw-in-base64-out \
  --payload '{
      "job_name": "seqcii_smlv_annotation",
      "tumor_name": "SEQC-II_Tumor_50pc",
      "normal_name": "SEQC-II_Normal",
      "tumor_bam": "s3://bucket-name/key-prefix/SEQC-II_Tumor_50pc-ready.bam",
      "normal_bam": "s3://bucket-name/key-prefix/SEQC-II_Normal-ready.bam",
      "tumor_smlv_vcf": "s3://bucket-name/key-prefix/SEQC-II-50pc-ensemble-annotated.vcf.gz",
      "output_dir": "s3://bucket-name/key-prefix/output/"
    }' \
  response.json
```

> The `output_dir` must target the output S3 bucket defined in `cdk.json` and contain the prefix
> `/gridss_purple_linx/`

#### Lambda arguments

| Argument              | Description                                                                                                   |
| ---                   | ---                                                                                                           |
| `job_name`            | Name for Batch job. Must be ≤128 characters and match this regex `^\w[\w_-]*$`.                               |
| `normal_name`         | Normal sample name. Must match **exactly** the normal name as it appears in provided the VCFs [*required*]    |
| `tumor_name`          | Tumor sample name. Must match **exactly** the tumor name as it appears in provided the VCFs [*required*]      |
| `tumor_bam`           | S3 path to normal BAM. Must be co-located with index. [*required*]                                            |
| `normal_bam`          | S3 path to tumor BAM. Must be co-located with index. [*required*]                                             |
| `tumor_smlv_vcf`      | S3 path to tumor small variant VCF.                                                                           |
| `tumor_sv_vcf`        | S3 path to tumor SV VCF. GRIDSS fragment extraction automatically run if provided.                            |
| `output_dir`          | S3 path to output directory. [*required*]                                                                     |
| `upload_nf_cache`     | Upload Nextflow work directory to output S3 path.                                                             |
| `docker_image_tag`    | Specific Docker image to use e.g. "0.0.3".                                                                    |
| `nextflow_args_str`   | Arguments to pass to Nextflow, must be wrapped in quotes e.g. `"\"--mem_gridss 14G\""`.                       |
| `instance_memory`     | Instance memory to provision.                                                                                 |
| `instance_vcpus`      | Instance vCPUs to provision. *Currently only accepting 8 vCPUs per job to avoid exceeding storage limits*.    |

### Manually generating LINX plots

Genes of interest are not always rendered in the default LINX plots. To force the inclusion of a gene, LINX plots can be
manually regenerated using the provided Lambda function. You must specify either a chromosome or cluster identifier
along with the appropriate gene symbol. Only genes present in the Ensembel data cache can be rendered.

```bash
aws lambda invoke \
  --function-name gpl_create_linx_plot \
  --cli-binary-format raw-in-base64-out \
  --payload '{
      "sample_id": "SEQC-II_Tumor_50pc",
      "cluster_ids": "0",
      "gene_ids": "ATAD1",
      "gpl_directory": "s3://bucket-name/key-prefix/"
    }' \
  response.json
```

The manually created LINX plots with be placed alongside the default LINX output, in the directory
`./linx/plots_manual/`.

#### Lambda arguments

| Argument          | Description                                                                               |
| ---               | ---                                                                                       |
| `sample_id`       | Name of sample. *Must* match LINX output file prefix.                                     |
| `cluster_ids`     | Comma-separated list of cluster identifiers to plot. Cannot be used with `chromosomes`.   |
| `chromsomes`      | Comma-separated list of chromosomes to plot. Cannot be used with `cluster_ids`.           |
| `gene_ids`        | Comma-separated list of genes to plot. Must be present in the Ensembel data cache.        |
| `gpl_directory`   | S3 path to the GRIDSS/PURPLE/LINX output.                                                 |
