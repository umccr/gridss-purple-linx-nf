FROM gridss/gridss:2.13.2

RUN \
  apt-get update && \
  apt-get install -y \
    cpanminus \
    libgd-dev \
    parallel && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

# Download HMF tools
ARG GH_BASE_URL=https://github.com/hartwigmedical/hmftools/releases/download
RUN \
  mkdir -p /opt/hmftools/ && \
  parallel -j5 --progress 'wget -q -O /opt/hmftools/$(echo {/} | sed "s/[-_].\+/.jar/") "${GH_BASE_URL}/{}"' ::: \
    amber-v3.7/amber.jar \
    cobalt-v1.11/cobalt-1.11.jar \
    gripss-v2.0/gripss.jar \
    purple-v3.2/purple_v3.2.jar \
    linx-v1.17/linx.jar

# Install R dependencies for HMF tools
# AMBER
#  - copynumber (bioconductor) [GRIDSS image]
# COBALT
#  - copynumber (bioconductor) [GRIDSS image]
# PURPLE
#  - dplyr [GRIDSS image]
#  - ggplot2 [GRIDSS image]
#  - VariantAnnotation (bioconductor) [GRIDSS image]
# Linx
#   - cowplot
#   - dplyr [GRIDSS image]
#   - ggplot2 [GRIDSS image]
#   - Gviz (bioconductor)
#   - magick
#   - tidyr
RUN \
  R -e " \
    install.packages( \
      pkgs=c( \
        'cowplot', \
        'magick', \
        'tidyr' \
      ), \
      repos='https://cloud.r-project.org/' \
    ); \
    BiocManager::install( \
      pkgs=c( \
        'Gviz' \
      ) \
    ) \
  "

# Install Circos, required dependency for Linx visualisation
# Conda and Ubuntu packages fail to install correctly
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
