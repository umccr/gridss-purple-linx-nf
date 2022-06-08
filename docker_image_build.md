# Docker image build instructions

```bash
VERSION=0.1.14
HUB_PROVIDER_URL=docker.io/scwatts
NAMES="gridss_deps gridss gpl"
# Build
for NAME in ${NAMES}; do
  docker build -t ${HUB_PROVIDER_URL}/${NAME}:${VERSION} -f docker/Dockerfile.${NAME} .;
done
# Upload
docker login
for NAME in ${NAMES}; do
  docker push ${HUB_PROVIDER_URL}/${NAME}:${VERSION};
done
```
