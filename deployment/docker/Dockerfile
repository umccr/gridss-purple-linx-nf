FROM scwatts/gpl:0.1.15

# Install lndir, only available through system package manager
RUN \
  apt-get update && \
  apt-get install -y --no-install-recommends xutils-dev && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

# Install pipeline dependencies
RUN \
  mamba install -y \
    -c umccr \
    -c bioconda \
    -c conda-forge \
    -c defaults \
    'bcftools ==1.14' \
    boto3 \
    nextflow \
    'r-gpgr ==1.3.1' \
    unzip && \
  mamba clean --all --force-pkgs-dirs --yes

# Install AWS CLI v2, appears to only be available through direct download
RUN \
  wget -O awscli.zip 'https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip' && \
  unzip awscli.zip && \
  ./aws/install --bin-dir /usr/bin && \
  rm -r awscli.zip aws/

# Install GPL pipeline
RUN \
    git clone https://github.com/umccr/gridss-purple-linx-nf /opt/gpl_pipeline/pipeline/ && \
    cd /opt/gpl_pipeline/pipeline/ && \
    rm -rf .git/ .gitignore deployment/ *.md Dockerfile nextflow.config
COPY assets/run_gpl.py /opt/gpl_pipeline/
COPY lambdas/layers/runtime/ /tmp/runtime/
COPY lambdas/layers/util/ /tmp/util/
RUN \
  pip install --no-cache-dir /tmp/runtime/ /tmp/util/ && \
  rm -r /tmp/runtime/ /tmp/util/

ENV PATH="/opt/gpl_pipeline:${PATH}"
