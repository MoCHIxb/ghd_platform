# 国护云｜校学生国旗护卫队社团管理平台

本项目是面向校学生国旗护卫队的独立数字化队务平台，采用 Flask、SQLAlchemy、JWT 与目录文件存储，实现活动执行、装备保障和办公室档案管理。

## 社团与组织背景

校学生国旗护卫队承担校园日常升旗、重要庆典出旗及爱国主义教育等任务。平台按实际协作流程设置三个部门：

- 综合办公室：队务协调、社交媒体入口、文件留档、活动素材审阅与管理。
- 教官部：升旗/出旗/训练项目创建、主教官移交、考勤、表现评分、总结和素材提交。
- 后勤部：设备分类登记、领用归还记录、实时库存及占用冲突提示。

## 角色与权限

- `member`（普通社员）：查看队务、参与活动、领用和归还本人设备。
- `minister`（部长）：拥有本部门业务管理权限。
- `captain`（队长）：拥有全队管理权限，并兼容原系统管理员接口。

活动项目另设“活动主教官”这一项目级权限。教官部部长可将单个项目移交给任意有效用户，主教官可独立维护该项目的考勤、评分、总结与素材。

## 已完成的第一版框架

- 全新国护队工作台与三部门入口，支持桌面端和移动端。
- 部门、成员身份及三级角色数据模型。
- 活动项目、项目成员、考勤评分、项目总结、活动素材及办公室审核模型和 API。
- 活动项目和设备支持封面图片上传，并在目录列表中直接展示。
- 父子级设备分类树、设备台账、领用归还记录和库存冲突校验。
- 社媒账号、文件档案、素材审阅队列。
- 提供独立的登录鉴权、通用文件上传、文件权限和访问记录能力。

## 技术栈

- 前端：原生 HTML、CSS、JavaScript 单页应用
- 后端：Python 3.10+、Flask、Flask-SQLAlchemy、Flask-JWT-Extended
- 数据库：MySQL 8+
- 鉴权：JWT + bcrypt

## 系统结构

```text
浏览器单页工作台（frontend）
        │ JSON / multipart + JWT
        ▼
Flask 蓝图接口（backend/routes）
  ├─ auth：账户与身份
  ├─ club：活动、设备、办公室业务
  └─ files：通用文件与媒体资源
        │
        ▼
SQLAlchemy 领域模型（backend/models.py）
        │
        ├─ MySQL：业务元数据、权限、分类和记录
        └─ uploads：文件、活动封面和设备图片
```

设备分类使用自关联结构，`equipment_category.parent_id` 指向上一级分类，可以继续扩展多层目录。活动封面保存在 `uploads/covers/activity`，设备图片保存在 `uploads/covers/equipment`，数据库仅保存随机文件名。

## 本地启动

```powershell
cd D:\国护队项目
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

配置数据库环境变量：

```powershell
$env:DB_HOST='127.0.0.1'
$env:DB_PORT='3306'
$env:DB_USER='root'
$env:DB_PASS='your_password'
$env:DB_NAME='ghd_platform'
$env:SECRET_KEY='change_me'
$env:JWT_SECRET_KEY='change_me_too'
```

首次运行请使用 Python 初始化脚本（不要使用旧版 `sql/init.sql`）：

```powershell
cd backend
..\.venv\Scripts\python.exe init_db.py
..\.venv\Scripts\python.exe app.py
```

浏览器访问 <http://127.0.0.1:5000>。

初始队长账号：

- 用户名：`captain`
- 密码：`Admin@123`

首次登录后请立即修改默认密码。

## 核心接口

| 模块 | 路径前缀 | 说明 |
|---|---|---|
| 认证 | `/api/auth` | 登录、资料、密码、头像 |
| 活动 | `/api/club/activities` | 项目、移交、考勤评分、总结、素材 |
| 后勤 | `/api/club/equipment` | 分类、台账、领用和归还 |
| 办公室 | `/api/club/office` | 社媒、档案、素材审阅 |
| 文件 | `/api/files` | 原系统文件上传、授权、下载和播放 |

## 后续迭代建议

当前版本以稳定的数据结构和部门工作流为主。后续适合逐步加入请假审批、训练计划、值班排班、消息通知、学期考评报表，以及将文件上传操作直接嵌入活动素材和办公室归档表单。
