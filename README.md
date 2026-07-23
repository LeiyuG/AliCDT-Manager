# 🛡️ AliCDT-Manager

阿里云 CDT 流量监控与自动化管理控制台

## ✨ 功能

- 多账户聚合监控，CDT 流量实时展示
- 流量熔断：超阈值自动停机
- (新增)余额待还熔断：到设置的待还余额值自动停机
- 停机模式有节省停机和普通停机，默认节省，可自选择
- 抢占式实例保活：被回收自动拉起
- 定时开关机计划
- Telegram 告警通知
- 账单统计（待还款金额，国际站准确）
- 浅色/深色主题切换
- 实例本地备注，日报始终可识别实例 ID

## 🔑 所需 RAM 权限

```bash
AliyunECSFullAccess
```
```bash
AliyunCDTFullAccess
```
```bash
AliyunBSSFullAccess
```

## 🚀 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/LeiyuG/AliCDT-Manager/main/install.sh)
```

安装完成后直接访问 `http://服务器IP:8000`，默认不需要配置 Nginx 反向代理。安装时可以输入其他端口。

> 请在云安全组或系统防火墙中仅向可信来源开放管理端口。若通过公网使用，仍建议配置 HTTPS。


## 🛠 手动部署

```bash
mkdir -p /app/alicdt-manager/data && cd /app/alicdt-manager
```
```bash
echo "SECRET_KEY=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 48)" > .env
```
```bash
curl -fsSL https://raw.githubusercontent.com/LeiyuG/AliCDT-Manager/main/docker-compose.yml -o docker-compose.yml
```
```bash
docker compose up -d
```

### 部署自行修改的源码

仓库默认使用官方预构建镜像；修改源码后需要构建自己的镜像：

```bash
cd frontend
npm install
npm run build
cd ..
docker build -t alicdt-manager:custom .
echo "IMAGE_NAME=alicdt-manager:custom" >> .env
docker compose up -d
```

默认监听所有网卡的 `8000` 端口，可直接访问：

```text
http://服务器IP:8000
```

如需更换端口，在 `.env` 中加入 `PORT=8080`。如需改回仅允许本机访问（用于 Nginx/Caddy 反代），加入 `BIND_ADDRESS=127.0.0.1`，然后执行：

```bash
docker compose up -d
```

已有部署若仍使用旧版 `127.0.0.1:8000:8000` 映射，请重新下载本仓库的 `docker-compose.yml`，或手动将端口映射改为：

```yaml
ports:
  - "0.0.0.0:8000:8000"
```

## ✨ 界面截图
![1](READMEimages/1.png)  
![2](READMEimages/2.png)  
![3](READMEimages/3.png)  
![5](READMEimages/5.png)  

## 可选：Nginx / Cloudflare 配置示例

直接通过端口访问时不需要本节。若需要域名和 HTTPS，请先在 `.env` 中设置 `BIND_ADDRESS=127.0.0.1`，再按需填写端口、域名和证书路径。

```bash
server {
    listen #端口 ssl;
    server_name #域名;

    ssl_certificate     #Pem证书路径;
    ssl_certificate_key #Key证书路径;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # 禁止访问数据目录
    location ^~ /data/ {
        deny all;
        return 403;
    }

    # 禁止访问 .env 等敏感文件
    location ~ /\. {
        deny all;
        return 403;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}

```

## Tech Stack

- Backend: Python + FastAPI + APScheduler + SQLite
- Frontend: Vue 3 + TailwindCSS
