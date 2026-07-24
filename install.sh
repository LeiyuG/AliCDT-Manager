#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=============================="
echo "   AliCDT Manager 一键安装"
echo -e "==============================${NC}"

# 检查并安装 Docker
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}未检测到 Docker，正在安装...${NC}"
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo -e "${GREEN}Docker 安装完成${NC}"
fi

# 询问端口
read -p "服务端口 [8000]: " PORT
PORT=${PORT:-8000}

# 创建目录
INSTALL_DIR="/root/docker/alicdt-manager"
mkdir -p "$INSTALL_DIR/data"
cd "$INSTALL_DIR"

# 生成随机密钥并配置直接访问端口
{
    echo "SECRET_KEY=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 48)"
    echo "BIND_ADDRESS=0.0.0.0"
    echo "PORT=${PORT}"
} > .env

# 下载 docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/LeiyuG/AliCDT-Manager/main/docker-compose.yml -o docker-compose.yml

# 启动
docker compose pull
docker compose up -d

echo -e "${GREEN}=============================="
echo "   安装完成！"
echo "   服务端口: ${PORT}"
echo "   访问地址: http://服务器IP:${PORT}"
echo "   默认可直接访问，无需配置 Nginx 反向代理"
echo "   首次访问请设置管理员账号"
echo -e "${YELLOW}   请在防火墙/安全组中仅向可信来源开放该端口${NC}"
echo -e "==============================${NC}"
