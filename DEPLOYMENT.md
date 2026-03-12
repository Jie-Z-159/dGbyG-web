# DGbyG 网站部署指南

## 快速部署（当前 - 使用IP访问）

### 1. 构建并启动服务
```bash
# 构建Docker镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 2. 访问方式
- **当前访问**: `http://YOUR_SERVER_IP`
- **健康检查**: `http://YOUR_SERVER_IP/health`

---

## 域名配置指南（dgbyg.drziweidai.com）

### 步骤1: 购买域名后的DNS配置
1. 在域名控制台添加A记录：
   ```
   主机记录: dgbyg
   记录类型: A
   记录值: YOUR_SERVER_IP
   TTL: 600
   ```

### 步骤2: 启用域名访问
修改 `nginx/conf.d/dgbyg.conf` 文件：
```bash
# 取消注释并修改server_name
server {
    listen 80;
    server_name dgbyg.drziweidai.com;  # 改为您的域名
    # ... 其他配置保持不变
}
```

### 步骤3: SSL证书配置（推荐）

#### 选项A: 使用Let's Encrypt免费证书
```bash
# 安装certbot
sudo apt-get update
sudo apt-get install certbot python3-certbot-nginx

# 停止docker-compose服务
docker-compose down

# 获取证书
sudo certbot certonly --standalone -d dgbyg.drziweidai.com

# 复制证书到项目目录
sudo cp /etc/letsencrypt/live/dgbyg.drziweidai.com/fullchain.pem nginx/ssl/dgbyg.drziweidai.com.crt
sudo cp /etc/letsencrypt/live/dgbyg.drziweidai.com/privkey.pem nginx/ssl/dgbyg.drziweidai.com.key
sudo chown $USER:$USER nginx/ssl/*
```

#### 选项B: 使用阿里云SSL证书
1. 在阿里云控制台购买/申请SSL证书
2. 下载Nginx格式证书
3. 将证书文件放入 `nginx/ssl/` 目录：
   ```
   nginx/ssl/dgbyg.drziweidai.com.crt
   nginx/ssl/dgbyg.drziweidai.com.key
   ```

### 步骤4: 启用HTTPS配置
编辑 `nginx/conf.d/dgbyg.conf`，取消注释HTTPS部分：
```nginx
# 取消注释HTTPS server块
server {
    listen 443 ssl http2;
    server_name dgbyg.drziweidai.com;

    ssl_certificate /etc/nginx/ssl/dgbyg.drziweidai.com.crt;
    ssl_certificate_key /etc/nginx/ssl/dgbyg.drziweidai.com.key;
    # ... 其他配置
}

# 取消注释HTTP重定向
server {
    listen 80;
    server_name dgbyg.drziweidai.com;
    return 301 https://$server_name$request_uri;
}
```

### 步骤5: 重启服务
```bash
# 重启服务应用新配置
docker-compose down
docker-compose up -d

# 检查状态
docker-compose ps
docker-compose logs nginx
```

---

## 管理命令

### 日常运维
```bash
# 查看服务状态
docker-compose ps

# 查看实时日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 更新代码后重新部署
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### 备份重要数据
```bash
# 备份上传文件
tar -czf uploads_backup_$(date +%Y%m%d).tar.gz uploads/

# 备份SSL证书
tar -czf ssl_backup_$(date +%Y%m%d).tar.gz nginx/ssl/
```

### 监控和调试
```bash
# 查看Nginx访问日志
tail -f nginx/logs/dgbyg_access.log

# 查看Nginx错误日志
tail -f nginx/logs/dgbyg_error.log

# 进入Flask容器调试
docker-compose exec flask-app bash

# 查看容器资源使用
docker stats
```

---

## 安全建议

1. **防火墙设置**: 只开放80和443端口
2. **定期更新**: 定期更新Docker镜像和系统包
3. **SSL证书续期**: Let's Encrypt证书90天有效期，需定期续期
4. **日志监控**: 定期检查访问日志，发现异常访问

---

## 故障排除

### 常见问题
1. **端口冲突**: 检查80/443端口是否被其他服务占用
2. **证书问题**: 检查证书文件路径和权限
3. **容器启动失败**: 检查docker-compose.yml配置

### 应急恢复
```bash
# 回滚到HTTP模式
# 注释掉HTTPS配置，重启服务
docker-compose restart nginx
```