#!/bin/bash
# ══════════════════════════════════════════════════════════════
# setup-server.sh — Persiapan Server AWS EC2 untuk Tugas Akhir
# ══════════════════════════════════════════════════════════════
# Script ini dijalankan otomatis oleh GitHub Actions CI/CD,
# atau manual saat setup pertama kali:
#   chmod +x setup-server.sh && ./setup-server.sh
#
# File .env di-inject otomatis oleh CI/CD dari GitHub Secrets.
# ══════════════════════════════════════════════════════════════

set -e

echo "══════════════════════════════════════════════════════════════"
echo "  🚀 Setup Server Tugas Akhir — AWS EC2"
echo "══════════════════════════════════════════════════════════════"

# --- 1. Detect Public IP (IMDSv2 compatible) ---
echo ""
echo "[1/5] Mendeteksi IP Public server..."
# IMDSv2 requires a token for security. Fallback to IMDSv1 if token fails.
IMDS_TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || echo "")

if [ -n "$IMDS_TOKEN" ]; then
    HOST_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" \
      http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "GAGAL_DETEKSI")
else
    HOST_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "GAGAL_DETEKSI")
fi
echo "      IP Public: $HOST_IP"

# --- 2. Create required directories ---
echo ""
echo "[2/5] Membuat direktori yang dibutuhkan..."
mkdir -p data saves models orchestration/dags
echo "      ✓ data/ saves/ models/ orchestration/dags/"

# --- 3. Add swap (if not exists) ---
echo ""
echo "[3/5] Mengecek swap memory..."
if [ "$(swapon --show | wc -l)" -lt 2 ]; then
    echo "      Menambahkan 4GB swap..."
    sudo fallocate -l 4G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    # Only add to fstab if not already there
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "      ✓ Swap 4GB aktif"
else
    echo "      ✓ Swap sudah ada"
fi

# --- 4. Resize filesystem (if EBS was expanded) ---
echo ""
echo "[4/5] Memeriksa filesystem..."
ROOT_DEVICE=$(df / | tail -1 | awk '{print $1}')
if command -v growpart &> /dev/null; then
    DISK_DEVICE=$(echo "$ROOT_DEVICE" | sed 's/p\?[0-9]*$//')
    PARTITION_NUM=$(echo "$ROOT_DEVICE" | grep -o '[0-9]*$')
    sudo growpart "$DISK_DEVICE" "$PARTITION_NUM" 2>/dev/null || true
    sudo resize2fs "$ROOT_DEVICE" 2>/dev/null || true
fi
echo "      ✓ Filesystem: $(df -h / | tail -1 | awk '{print $2}') total, $(df -h / | tail -1 | awk '{print $4}') free"

# --- 5. Verify .env exists ---
echo ""
echo "[5/5] Verifying .env..."
if [ ! -f .env ]; then
    echo "      ❌ File .env BELUM ADA!"
    echo "      File .env di-generate otomatis oleh GitHub Actions CI/CD."
    echo "      Jika setup manual, salin dari template:"
    echo ""
    echo "      cp .env.example .env   # lalu isi kredensial"
    echo ""
    exit 1
else
    # Count secrets (non-empty, non-comment lines)
    SECRET_COUNT=$(grep -c '^[A-Z]' .env || echo 0)
    echo "      ✅ .env ready ($SECRET_COUNT variables loaded)"
fi

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  ✅ Setup selesai! Jalankan deployment dengan:"
echo ""
echo "  docker compose -f docker-compose.prod.yml --profile etl up -d --build"
echo ""
echo "  Akses aplikasi:"
echo "    Frontend : http://$HOST_IP"
echo "    Airflow  : http://$HOST_IP:8080"
echo "══════════════════════════════════════════════════════════════"
