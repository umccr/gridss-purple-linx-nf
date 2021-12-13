# Docker image build instructions
## Build
```bash
# Set build and upload info
NAME=gpl
VERSION=0.0.3
URI_LOCAL="${NAME}:${VERSION}"
# Docker Hub
HUB_PROVIDER_URL=docker.io/scwatts
HUB_URI_REMOTE="${HUB_PROVIDER_URL}/${NAME}:${VERSION}"
```

```bash
docker build -t "${NAME}" -f Dockerfile .
```

## Upload
```bash
# Tag image with remote Docker Hub URI
docker tag "${NAME}" "${HUB_URI_REMOTE}"

# Configure Docker with DH credentials and upload
docker login
docker push "${HUB_URI_REMOTE}"

# Remove unencrypted credentials
rm /Users/stephen/.docker/config.json
```
