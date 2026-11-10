#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.noarmor.gpg -o /etc/apt/keyrings/tailscale.gpg
echo "deb [signed-by=/etc/apt/keyrings/tailscale.gpg] https://pkgs.tailscale.com/stable/ubuntu ${VERSION_CODENAME} main" > /etc/apt/sources.list.d/tailscale.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin tailscale
systemctl enable --now docker tailscaled
# Use a tagged, short-lived auth key and restrict SSH with your tailnet policy.
tailscale up --auth-key='__TS_AUTHKEY__' --ssh
# The auth key remains in cloud-init user-data; rotate/revoke it after first join.
chmod 0600 /opt/ghost/compose.yaml
cd /opt/ghost
docker compose pull
docker compose up -d
