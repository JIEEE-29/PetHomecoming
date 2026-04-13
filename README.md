# 宠物归家系统 Pet Homecoming

## 项目简介

宠物归家系统是一个面向流浪宠物救助、走失宠物寻回、领养发布与人员审核场景的前后端分离 Web 系统。项目采用原生前端与 Python 轻量后端实现，适合课程设计、毕业设计和原型演示。

当前版本已经完成以下核心流程：

- 用户注册、登录、账户信息查看
- 管理员审核注册人员资料
- 宠物图片本地上传、图片处理与自动识别
- 宠物档案发布、筛选浏览与详情查看
- 帖子评论、救治联系、领养申请、认领联系

## 当前页面结构

系统前端已按实际使用流程拆分为多个页面，不再把所有内容堆在一个页面中。

- `frontend/index.html`
  - 首页直接展示宠物库内容
  - 支持按关键词、分类、状态筛选帖子
  - 顶部导航只保留“首页 / 账户中心 / 审核后台”
  - “宠物发布”按钮位于首页“宠物库”标题旁
- `frontend/auth.html`
  - 只显示当前登录用户资料与退出登录
  - 不再显示注册和登录表单
- `frontend/login.html`
  - 独立登录页
  - 页面下方提供注册入口
- `frontend/register.html`
  - 独立注册页
- `frontend/publish.html`
  - 当前只保留本地图片上传
  - 已移除摄像头拍照入口
  - 上传后自动生成预览、处理结果和识别分析
- `frontend/pet-detail.html`
  - 评论区和救治/领养/认领联系信息仅在详情页显示
- `frontend/admin.html`
  - 管理员审核待处理用户资料

## 核心功能

### 1. 用户与审核

- 用户可注册基础身份信息
- 已审核通过的用户可登录系统
- 登录后前端通过 Bearer Token 调用后端接口
- 管理员可在审核后台对用户执行通过或驳回操作

### 2. 宠物发布

- 发布页只支持本地图片上传
- 前端生成原图预览和处理后预览
- 用户填写宠物名称、分类、状态、地点、描述、联系电话等信息后发布档案

### 3. 图像识别

- 后端提供图片识别接口
- 上传图片后会尝试识别猫、狗、鸟等宠物大类
- 识别结果用于辅助填写宠物分类
- 系统保留人工手动调整分类的能力

说明：当前版本的识别主要用于“宠物大类辅助识别”，不是完整的品种级识别系统。

### 4. 宠物库与帖子详情

- 首页直接显示宠物帖子列表
- 列表页只展示摘要信息，不再展开评论区和联系表单
- 用户点击帖子后进入详情页查看完整信息
- 详情页中可发表评论、提交救治联系、领养申请和认领联系

## 技术栈

- 前端：HTML + CSS + JavaScript
- 后端：Python 标准库 `ThreadingHTTPServer`
- 数据库：MySQL 8.0
- 数据访问：PyMySQL
- 图片处理：Pillow
- 目标识别：Ultralytics YOLO

## 项目目录

```text
pet-homecoming/
├─ backend/
│  ├─ server.py
│  ├─ requirements.txt
│  ├─ pet_homecoming.db  # 历史 SQLite 数据源，首次启动可迁移
│  ├─ models/
│  └─ uploads/
├─ frontend/
│  ├─ index.html
│  ├─ auth.html
│  ├─ login.html
│  ├─ register.html
│  ├─ publish.html
│  ├─ pets.html
│  ├─ pet-detail.html
│  ├─ admin.html
│  ├─ app.js
│  ├─ config.js
│  └─ style.css
└─ README.md
```

## 本地运行方式

### 1. 启动后端

先按实际 MySQL 环境配置连接参数：

```powershell
$env:PET_HOME_DB_HOST="127.0.0.1"
$env:PET_HOME_DB_PORT="3306"
$env:PET_HOME_DB_USER="你的MySQL用户名"
$env:PET_HOME_DB_PASSWORD="你的MySQL密码"
$env:PET_HOME_DB_NAME="pet_homecoming"
```

然后启动后端：

```powershell
cd E:\Codex\pet-homecoming\backend
python server.py
```

启动成功后可访问：

- <http://127.0.0.1:8000/api/health>

说明：

- 后端现在默认使用 MySQL，不再直接把 SQLite 作为运行时数据库
- 若 `backend/pet_homecoming.db` 存在，且 MySQL 是空库，系统首次启动时会自动尝试迁移旧 SQLite 数据
- MySQL 连接依赖 `PyMySQL`，已写入 `backend/requirements.txt`

### 1.1 数据迁移说明

- 历史数据文件仍保留在 `backend/pet_homecoming.db`
- 当前运行时数据库为 MySQL
- 系统首次启动时会自动尝试迁移以下表数据：
  - `users`
  - `sessions`
  - `pets`
  - `comments`
  - `contacts`
- 迁移完成后，后续接口读写都以 MySQL 为准

### 2. 启动前端

```powershell
cd E:\Codex\pet-homecoming\frontend
python -m http.server 5173
```

前端入口：

- <http://127.0.0.1:5173/index.html>
- <http://127.0.0.1:5173/login.html>
- <http://127.0.0.1:5173/register.html>
- <http://127.0.0.1:5173/publish.html>
- <http://127.0.0.1:5173/admin.html>

### 默认管理员账号

- 用户名：`admin`
- 密码：`admin123`

## 主要业务流程

### 用户注册与审核

1. 用户在注册页填写身份信息并提交。
2. 后端将用户状态保存为待审核。
3. 管理员登录后台审核用户资料。
4. 审核通过后，用户可登录系统。

### 宠物发布

1. 用户进入宠物发布页并上传本地图片。
2. 前端展示原图与处理后预览。
3. 前端调用后端识别接口获取分类辅助结果。
4. 用户补充宠物名称、状态、地点、描述和联系方式。
5. 提交后生成宠物帖子。

### 宠物浏览与联系

1. 用户在首页筛选并浏览宠物帖子。
2. 点击帖子进入详情页。
3. 在详情页查看评论与联系信息。
4. 登录用户可发表评论或提交联系申请。

## 当前版本说明

当前仓库以“可运行、可演示、页面流程完整”为目标，近期已经完成以下前端调整：

- 首页直接承载宠物库内容
- 宠物发布入口从顶部导航调整到首页宠物库标题旁
- 详情信息从列表页折叠为独立详情页展示
- 发布页收敛为本地上传模式
- 帖子列表样式、间距和历史分类乱码已修复

## 后续可扩展方向

- 增加更完整的 JWT 鉴权与刷新机制
- 将 YOLO 扩展为检测加品种分类的两阶段模型
- 增加图片相似度匹配和走失宠物比对能力
- 将 MySQL 进一步升级为 PostgreSQL 或更完整的分布式架构
- 增加操作日志、通知提醒和统计报表
