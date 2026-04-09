#!/bin/bash
set -e

IMAGE_TAG=$1

if [ -z "$IMAGE_TAG" ]; then
    echo -e "\033[31mError: Image tag is required\033[0m"
    exit 1
fi

echo -e "\033[32mPulling image: $IMAGE_TAG\033[0m"

SLASH_COUNT=$(echo "$IMAGE_TAG" | tr -cd '/' | wc -c)

case $SLASH_COUNT in
    0)
        MIRROR_URL="m.daocloud.io/docker.io/library"
        echo -e "\033[36mImage format: Official image (no prefix)\033[0m"
        ;;
    1)
        MIRROR_URL="m.daocloud.io/docker.io"
        echo -e "\033[36mImage format: Hub repository (one prefix)\033[0m"
        ;;
    *)
        MIRROR_URL="m.daocloud.io"
        echo -e "\033[36mImage format: Third-party registry (multiple prefixes)\033[0m"
        ;;
esac

FULL_MIRROR_URL="$MIRROR_URL/$IMAGE_TAG"
echo -e "\033[33mMirror URL: $FULL_MIRROR_URL\033[0m"

echo -e "\033[34mStep 1: Pulling image from mirror...\033[0m"
docker pull "$FULL_MIRROR_URL"

echo -e "\033[34mStep 2: Tagging image with original name...\033[0m"
docker tag "$FULL_MIRROR_URL" "$IMAGE_TAG"

echo -e "\033[34mStep 3: Removing mirror tag...\033[0m"
docker rmi "$FULL_MIRROR_URL"

echo -e "\n\033[32mProcess completed successfully!\033[0m"
