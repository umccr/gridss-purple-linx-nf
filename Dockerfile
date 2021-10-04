FROM gridss/gridss:2.12.1

RUN \
  apt-get update && \
  apt-get install -y \
    cpanminus \
    libgd-dev \
    libmagick++-dev && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

# Download HMF tools
ARG GH_DOWNLOAD_URL_PREFIX=https://github.com/hartwigmedical/hmftools/releases/download
RUN \
  echo 'Retrieving required HMF tools' && \
  wget --quiet --directory-prefix /opt/hmftools/ "${GH_DOWNLOAD_URL_PREFIX}/amber-v3.5/amber-3.5.jar" & \
  wget --quiet --directory-prefix /opt/hmftools/ "${GH_DOWNLOAD_URL_PREFIX}/cobalt-v1.11/cobalt-1.11.jar" & \
  wget --quiet --directory-prefix /opt/hmftools/ "${GH_DOWNLOAD_URL_PREFIX}/gripss-v1.11/gripss-1.11.jar" & \
  wget --quiet --directory-prefix /opt/hmftools/ "${GH_DOWNLOAD_URL_PREFIX}/purple-v3.1/purple_v3.1.jar" & \
  wget --quiet --directory-prefix /opt/hmftools/ "${GH_DOWNLOAD_URL_PREFIX}/linx-v1.16/linx_v1.16.jar" & \
  wait

# Install R dependencies for HMF tools
# AMBER v3.5
#  - copynumber (bioconductor)
# COBALT v1.11
#  - copynumber (bioconductor)
# SAGE v2.8
#  - dplyr
#  - ggplot2
#  - tidyr
# PURPLE v3.1
#  - dplyr
#  - ggplot2
#  - VariantAnnotation (bioconductor)
# Linx v1.16
#   - cowplot
#   - dplyr
#   - ggplot2
#   - magick
#   - tidyr
#   - Gviz (bioconductor)
# NOTE: many R packages provisioned by GRIDSS Dockerfile, listing here to be explicit
RUN \
  R -e " \
    install.packages( \
      pkgs=c( \
        'cowplot', \
        'dplyr', \
        'ggplot2', \
        'magick', \
        'tidyr' \
      ), \
      repos='https://cloud.r-project.org/' \
    ); \
    library(BiocManager); \
    BiocManager::install( \
      pkgs=c( \
        'copynumber', \
        'Gviz', \
        'VariantAnnotation' \
      ) \
    ) \
  "

# Install Circos, required dependency for Linx visualisation
RUN \
  mkdir -p /opt/circos/ && \
  cd /opt/circos/ && \
    wget http://circos.ca/distribution/circos-0.69-9.tgz && \
    tar --strip-components 1 -zxvf circos-0.69-9.tgz && \
    rm circos-0.69-9.tgz && \
  cpanm \
    Clone \
    Config::General \
    Font::TTF::Font \
    GD \
    GD::Polyline \
    Math::Bezier \
    Math::Round \
    Math::VecStat \
    Regexp::Common \
    SVG \
    Set::IntSpan \
    Statistics::Basic \
    Text::Format && \
  rm -r /root/.cpanm/

# Install newer and complete release of RepeatMasker-patched BLAST (rmBLAST)
# The GRIDSS Dockerfile only installs the rmblast binary and RepeatMasker attempts to run the rmBLAST makeblastdb, which doesn't exist
RUN \
  cd /opt/rmblast && \
  rm ./* && \
  wget http://www.repeatmasker.org/rmblast-2.11.0+-x64-linux.tar.gz && \
  tar --no-anchored --strip-components 2 -xvzf rmblast-2.11.0+-x64-linux.tar.gz rmblastn makeblastdb && \
  rm rmblast-2.11.0+-x64-linux.tar.gz
