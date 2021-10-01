FROM scwatts/gpl:latest

RUN \
  apt-get update && \
  apt-get install -y git python3-pip xutils-dev  && \
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
    git clone https://github.com/ummcr/gridss-purple-linx-nf /opt/gpl/ && \
    cd /opt/gpl/ && \
    rm -rf .git/ .gitignore cdk_app/ && \
    mv nf_pipeline/ pipeline/

COPY run_gpl.py /opt/gpl/

ENV PATH="/opt/gpl:/opt/nextflow:${PATH}"
