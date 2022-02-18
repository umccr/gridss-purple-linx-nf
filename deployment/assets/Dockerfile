FROM scwatts/gpl:0.1.4

RUN \
  apt-get update && \
  apt-get install -y git python3-pip graphviz pandoc xutils-dev  && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

RUN \
  pip3 install boto3 && \
  rm -r /root/.cache/pip

# NOTE(SW): only the Conda package copies gpgr.R into a PATH directory
RUN \
  R -e " \
    install.packages('remotes'); \
    remotes::install_github('umccr/gpgr', ref='v1.2.1', dependencies=TRUE)\
  " && \
  wget -P /usr/local/bin/ https://raw.githubusercontent.com/umccr/gpgr/v1.2.1/inst/cli/gpgr.R && \
  chmod 755 /usr/local/bin/gpgr.R

RUN \
  mkdir -p /opt/nextflow && \
  cd /opt/nextflow && \
  wget -O nextflow https://github.com/nextflow-io/nextflow/releases/download/v21.04.3/nextflow-21.04.3-all && \
  chmod 700 nextflow

RUN \
  wget -O awscli.zip 'https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip' && \
  unzip awscli.zip && \
  ./aws/install --bin-dir /usr/bin && \
  rm -r awscli.zip aws/

RUN \
    git clone https://github.com/umccr/gridss-purple-linx-nf.git /opt/gpl/pipeline/ && \
    cd /opt/gpl/pipeline/ && \
    rm -rf .git/ .gitignore deployment/ *.md Dockerfile nextflow.config

COPY assets/run_gpl.py /opt/gpl/

ENV PATH="/opt/gpl:/opt/nextflow:${PATH}"
