# 宠物归家系统

一个面向宠物寻回、救助、领养协同场景的轻量 Web 系统，基于 `Python 标准库 + SQLite + 原生 HTML/CSS/JavaScript` 实现，开箱即用，不依赖额外后端框架。

项目目标是把“人员注册审核”“宠物发布”“宠物检索互动”“后台审批”拆成清晰的业务页面，而不是堆在单一页面里，便于后续继续扩展。

## 功能概览

### 1. 人员注册、登录、资料审核

- 普通用户可注册账号并填写基础资料
- 新注册用户默认进入 `pending` 审核状态
- 只有审核通过的用户才允许登录系统
- 管理员可在后台完成资料审批

### 2. 拍照、图片处理与上传

- 支持浏览器摄像头抓拍
- 支持从本地选择图片上传
- 前端会生成原图和处理后图片
- 同时提取基础图像指标：
  - 亮度
  - 对比度
  - 平均 RGB
  - 主导色倾向
  - 清晰度等级

### 3. 宠物分类与状态识别

- 支持人工填写宠物分类、状态、品种、发现地点和描述
- 系统会结合文本关键词和图像分析做规则识别
- 自动输出：
  - 识别分类
  - 识别状态
  - 识别说明
  - 后续处理建议

### 4. 评论、救治联系、领养与认领

- 用户可在宠物档案下发表评论
- 可提交三种联系申请：
  - `rescue` 救治联系
  - `adoption` 领养申请
  - `claim` 认领联系

## 页面结构

系统已拆分为多页面：

- `/`
  - 首页，展示系统入口与概览信息
- `/auth`
  - 账户中心，处理注册、登录、查看当前用户状态
- `/publish`
  - 宠物发布页，处理拍照、图片分析和建档
- `/pets`
  - 宠物库，浏览宠物、评论互动、提交联系申请
- `/admin`
  - 审核后台，仅管理员用于审批注册资料

## 技术栈

- 后端：Python 标准库
  - `http.server`
  - `sqlite3`
  - `hashlib`
- 数据库：SQLite
- 前端：原生 HTML / CSS / JavaScript
- 图片处理：浏览器 Canvas

## 项目结构

```text
pet-homecoming/
├─ server.py
├─ README.md
├─ .gitignore
├─ static/
│  ├─ index.html
│  ├─ auth.html
│  ├─ publish.html
│  ├─ pets.html
│  ├─ admin.html
│  ├─ app.js
│  └─ style.css
└─ uploads/
   └─ .gitkeep
```

## 本地运行

### 1. 进入项目目录

```powershell
cd E:\Codex\pet-homecoming
```

### 2. 启动服务

```powershell
python server.py
```

启动成功后访问：

- [http://127.0.0.1:8000](http://127.0.0.1:8000)

其他页面入口：

- [http://127.0.0.1:8000/auth](http://127.0.0.1:8000/auth)
- [http://127.0.0.1:8000/publish](http://127.0.0.1:8000/publish)
- [http://127.0.0.1:8000/pets](http://127.0.0.1:8000/pets)
- [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin)

## 默认管理员账号

- 用户名：`admin`
- 密码：`admin123`

首次启动时，系统会自动初始化数据库并创建该管理员账号。

## 数据存储

- SQLite 数据库文件：`pet_homecoming.db`
- 上传图片目录：`uploads/`

说明：

- 数据库文件默认不会提交到 GitHub
- 上传目录默认只保留 `.gitkeep`

## 主要业务流程

### 普通用户流程

1. 在 `/auth` 页面注册账号
2. 等待管理员审核
3. 审核通过后登录
4. 在 `/publish` 页面上传宠物照片并创建档案
5. 在 `/pets` 页面查看宠物库、发表评论或提交联系申请

### 管理员流程

1. 使用默认管理员账号登录
2. 打开 `/admin` 页面查看待审核用户
3. 审核通过或驳回注册资料

## 当前实现说明

### 已实现

- 多页面结构
- 基础用户鉴权
- 资料审核状态控制
- 宠物档案创建
- 评论发布
- 救治/领养/认领联系单提交
- 基于规则的宠物分类与状态识别
- 图片基础分析与预处理

### 当前识别逻辑的定位

目前宠物识别为 MVP 版本，不是深度学习模型识别，主要用于打通业务流程。识别结果来自：

- 文本关键词匹配
- 图片亮度/对比度等规则分析

后续可以替换为真实的图像识别或多模态模型接口。

## 可扩展方向

- 接入真实宠物图像识别模型
- 增加短信、邮件或微信通知
- 增加联系单处理状态流转
- 增加宠物详情独立页面
- 增加管理员对宠物档案的审核功能
- 增加角色权限细分
- 拆分为前后端分离架构
- 替换 SQLite 为 MySQL / PostgreSQL

## 开发说明

### 后端入口

- [server.py](./server.py)

### 前端入口

- [static/index.html](./static/index.html)
- [static/auth.html](./static/auth.html)
- [static/publish.html](./static/publish.html)
- [static/pets.html](./static/pets.html)
- [static/admin.html](./static/admin.html)

### 样式与交互

- 共享脚本：[static/app.js](./static/app.js)
- 共享样式：[static/style.css](./static/style.css)

## 许可证

当前仓库未单独声明许可证，如需开源发布，建议补充 `LICENSE` 文件。
