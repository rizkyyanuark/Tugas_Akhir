#!/bin/bash
# Prepare the EC2 host for the production Docker Compose stack.
# GitHub Actions generates .env and Cloudflare Tunnel config before this runs.

set -e

echo "== YUNESA production host setup =="

echo ""
echo "[1/5] Detecting EC2 public IP..."
IMDS_TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || echo "")

if [ -n "$IMDS_TOKEN" ]; then
    HOST_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" \
      http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "not-detected")
else
    HOST_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "not-detected")
fi
echo "      public_ip=$HOST_IP"

echo ""
echo "[2/5] Creating runtime directories..."
mkdir -p data saves models orchestration/dags cloudflared
echo "      runtime directories ready"

echo ""
echo "[3/5] Checking swap..."
if [ "$(swapon --show | wc -l)" -lt 2 ]; then
    echo "      creating 4GB swapfile"
    sudo fallocate -l 4G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
else
    echo "      swap already active"
fi

echo ""
echo "[4/5] Checking root filesystem..."
ROOT_DEVICE=$(df / | tail -1 | awk '{print $1}')
if command -v growpart >/dev/null 2>&1; then
    DISK_DEVICE=$(echo "$ROOT_DEVICE" | sed 's/p\?[0-9]*$//')
    PARTITION_NUM=$(echo "$ROOT_DEVICE" | grep -o '[0-9]*$')
    sudo growpart "$DISK_DEVICE" "$PARTITION_NUM" 2>/dev/null || true
    sudo resize2fs "$ROOT_DEVICE" 2>/dev/null || true
fi
echo "      filesystem=$(df -h / | tail -1 | awk '{print $2}') free=$(df -h / | tail -1 | awk '{print $4}')"

echo ""
echo "[5/5] Verifying generated deployment files..."
test -s .env || {
    echo "      missing .env"
    exit 1
}
test -s cloudflared/config.yaml || {
    echo "      missing cloudflared/config.yaml"
    exit 1
}
test -s cloudflared/credentials.json || {
    echo "      missing cloudflared/credentials.json"
    exit 1
}
# The official cloudflared image runs as non-root 65532:65532. Keep the
# credential file private, but make its owner match the container user so the
# tunnel can read it after GitHub Actions regenerates the runtime files.
chmod 644 cloudflared/config.yaml
sudo chown 65532:65532 cloudflared/credentials.json
sudo chmod 600 cloudflared/credentials.json
SECRET_COUNT=$(grep -c '^[A-Z]' .env || echo 0)
echo "      env_variables=$SECRET_COUNT cloudflare_tunnel_config=ready"

echo ""
echo "Setup complete."
echo "Production access is routed through Cloudflare Tunnel:"
echo "  frontend https://app.tugasakhir.space"
echo "  api      https://api.tugasakhir.space"
echo "  airflow  https://airflow.tugasakhir.space"
