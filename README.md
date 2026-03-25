# SimonDPhotograph

SimonDPhotograph 的网站源码与部署文件。

![SimonDPhotograph Preview](./thumbs/DSC_0399.JPG)

当前线上入口：

- 首页：`https://simond.photo/`
- 摄影作品页：`https://simond.photo/cheungchau.html`
- 站主统计页：`https://simond.photo/admin-stats.html`
- 摄影站 API：`https://simond.photo/api/...`
- Gemini 子站：`https://gemini.simond.photo/`

## 目录说明

- `index.html`
  - 首页
- `cheungchau.html`
  - 长洲摄影作品页
- `admin-stats.html`
  - 站主专用统计页
- `api_server.py`
  - 点赞、评论、站主登录、统计、地图代理等接口
- `cheungchau-api.service`
  - systemd 服务配置
- `nginx-default.conf`
  - Nginx 站点配置
- `cheungchaw/`
  - 原图目录
- `thumbs/`
  - 缩略图目录
- `vendor/leaflet/`
  - 地图前端依赖

## 站主功能

站主权限统一挂在 `simond.photo` 根域名下，主要接口包括：

- `/api/admin/status`
- `/api/admin/login`
- `/api/admin/logout`
- `/api/admin/stats`
- `/api/admin/server-status`

站主登录后可在首页、作品页和统计页共用登录状态。

## 本地开发

如果只需要改静态页面，直接编辑这些文件即可：

- `index.html`
- `cheungchau.html`
- `admin-stats.html`

如果需要改摄影站接口：

- 编辑 `api_server.py`
- 同步到服务器后重启 `cheungchau-api`

## 部署说明

当前线上服务器：

- SSH Host: `Tokyo`
- Domain: `simond.photo`
- Web Root: `/var/www/html`
- API Service: `cheungchau-api`

### 常用文件上传

```powershell
scp .\index.html Tokyo:/var/www/html/index.html
scp .\cheungchau.html Tokyo:/var/www/html/cheungchau.html
scp .\admin-stats.html Tokyo:/var/www/html/admin-stats.html
scp .\api_server.py Tokyo:/var/www/html/api_server.py
scp .\robots.txt Tokyo:/var/www/html/robots.txt
scp .\sitemap.xml Tokyo:/var/www/html/sitemap.xml
```

### 上传整组静态资源

```powershell
scp -r .\thumbs Tokyo:/var/www/html/
scp -r .\cheungchaw Tokyo:/var/www/html/
scp -r .\vendor Tokyo:/var/www/html/
```

### 服务重启

```powershell
ssh Tokyo "systemctl restart cheungchau-api"
ssh Tokyo "systemctl reload nginx"
```

### 检查线上状态

```powershell
ssh Tokyo "systemctl is-active cheungchau-api"
ssh Tokyo "nginx -t"
ssh Tokyo "curl -I -s https://simond.photo/"
ssh Tokyo "curl -I -s https://simond.photo/cheungchau.html"
ssh Tokyo "curl -I -s https://simond.photo/admin-stats.html"
```

### 典型发布流程

```powershell
git status
git add .
git commit -m "your message"
git push

scp .\index.html Tokyo:/var/www/html/index.html
scp .\cheungchau.html Tokyo:/var/www/html/cheungchau.html
scp .\admin-stats.html Tokyo:/var/www/html/admin-stats.html
scp .\api_server.py Tokyo:/var/www/html/api_server.py
ssh Tokyo "systemctl restart cheungchau-api && systemctl reload nginx"
```

## Git 工作流

```powershell
git status
git add .
git commit -m "your message"
git push
```

当前默认分支：

- `main`

## 备注

- `backups/` 不纳入 Git 版本库
- `remote-*.conf` 为临时远端配置副本，不纳入 Git 版本库
- 当前仓库已接到 GitHub：`https://github.com/SimonD0711/simond-photo.git`

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE).
