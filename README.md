# 宠物归家系统

当前仓库已经拆分为前后端分离架构：

- `backend/` 只负责 API、鉴权、SQLite 数据库、图片上传资源
- `frontend/` 只负责页面展示和浏览器端交互，通过 `API_BASE` 调用后端接口

这意味着前端和后端可以独立启动、独立部署，也便于后续替换任意一侧的实现。

## 架构说明

### 后端

后端目录：`backend/`

职责：

- 用户注册、登录、资料审核
- 宠物档案创建与查询
- 评论与联系申请
- 宠物分类和状态规则识别
- 图片上传与静态访问
- SQLite 数据持久化

后端接口前缀：

- `/api/*`
- `/uploads/*`

默认地址：

- `http://127.0.0.1:8000`

### 前端

前端目录：`frontend/`

职责：

- 首页、账户中心、宠物发布、宠物库、审核后台页面
- 摄像头拍照和图片基础处理
- 调用后端 API 并渲染数据
- 管理浏览器端登录态

前端通过 `frontend/config.js` 中的 `API_BASE` 指向后端：

```js
window.APP_CONFIG = {
  API_BASE: "http://127.0.0.1:8000",
};
```

## 目录结构

```text
pet-homecoming/
├─ backend/
│  ├─ server.py
│  └─ uploads/
│     └─ .gitkeep
├─ frontend/
│  ├─ index.html
│  ├─ auth.html
│  ├─ publish.html
│  ├─ pets.html
│  ├─ admin.html
│  ├─ app.js
│  ├─ config.js
│  └─ style.css
├─ .gitignore
└─ README.md
```

## 本地运行

### 1. 启动后端

```powershell
cd E:\Codex\pet-homecoming\backend
python server.py
```

启动后端后，API 地址为：

- [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

### 2. 启动前端

另开一个终端：

```powershell
cd E:\Codex\pet-homecoming\frontend
python -m http.server 5173
```

然后访问：

- [http://127.0.0.1:5173](http://127.0.0.1:5173)

前端页面入口：

- [http://127.0.0.1:5173/index.html](http://127.0.0.1:5173/index.html)
- [http://127.0.0.1:5173/auth.html](http://127.0.0.1:5173/auth.html)
- [http://127.0.0.1:5173/publish.html](http://127.0.0.1:5173/publish.html)
- [http://127.0.0.1:5173/pets.html](http://127.0.0.1:5173/pets.html)
- [http://127.0.0.1:5173/admin.html](http://127.0.0.1:5173/admin.html)

## 默认管理员账号

- 用户名：`admin`
- 密码：`admin123`

## 现有功能

- 人员注册、登录、资料审核
- 浏览器拍照、本地图片上传、图像基础处理
- 宠物分类与状态识别
- 宠物评论
- 救治联系、领养申请、认领联系
- 多页面前端
- API-only 后端

## 后续可扩展方向

- 将前端替换为 Vue / React / Next.js
- 将后端替换为 FastAPI / Django / Flask
- 将 SQLite 替换为 MySQL / PostgreSQL
- 增加 JWT 或更完整的鉴权机制
- 增加宠物详情独立页面
- 增加消息通知和审核流转
