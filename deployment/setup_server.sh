#!/bin/bash
# ==========================================
# 🚀 AWS EC2 SERVER INITIALIZATION
# ==========================================
# This script ensures the server is ready for 
# Docker Compose V2 and cleans up old data.

echo "🔍 Checking Docker and AWS CLI installation..."

# 1. Update package list if needed
sudo apt-get update -y

# 2. Ensure Docker exists and is compatible with Compose V2
if ! command -v docker &> /dev/null; then
    echo "📦 Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo apt install -y docker-compose-plugin
fi

# 2.5 Ensure AWS CLI exists for ECR login
if ! command -v aws &> /dev/null; then
    echo "📦 Installing AWS CLI..."
    sudo apt-get install -y awscli
fi

# 3. Add user 'ubuntu' to docker group so we don't need 'sudo' every time
if ! groups ubuntu | grep -q "\bdocker\b"; then
    echo "👤 Adding 'ubuntu' to docker group..."
    sudo usermod -aG docker ubuntu
    echo "⚠️  Note: You might need to restart your session for group changes to apply."
fi

# 4. GENTLE CLEANUP (Best Practice)
# Only removes dead containers, dangling images, and unused networks.
# Does NOT remove volumes (your data is safe).
echo "🧹 Performing gentle cleanup of unused Docker resources..."
sudo docker system prune -f

# 5. Verify versions
echo "✅ Versions installed:"
docker --version
docker compose version
aws --version

echo "🚀 Server is ready!"
