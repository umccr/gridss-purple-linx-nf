FROM scwatts/gpl:0.0.3

RUN \
  apt-get update && \
  apt-get install -y git python3-pip graphviz xutils-dev  && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

RUN \
  pip3 install boto3 && \
  rm -r /root/.cache/pip

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
