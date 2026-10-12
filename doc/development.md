生成日期：2026-10-12

文档概要：提供通用配置、开发启动、数据库迁移、客户端构建和现有测试的执行方法。

# 安装、开发与验证

以下命令从仓库根目录执行，子项目命令会注明工作目录。示例站点是占位地址，运行前需替换为自己的服务配置。

## 环境准备

- Python 3.11 或更高版本，以及 [requirements.txt](../requirements.txt) 中的依赖。
- MySQL 数据库和具有该数据库访问权限的应用账号。
- Node.js 22.12 或更高版本，使用子项目锁文件安装依赖。
- 构建 Android 时需要 JDK、Android SDK Platform 35 及平台工具；建议使用 JDK 21。
- Office 预览需要服务端 LibreOffice，可通过 `PATH` 中的 `soffice`、`libreoffice` 或 `SOFFICE_BIN` 配置定位；信息中心及媒体处理按启用的功能另外配置所需外部服务或工具。

## 后端配置与启动

创建虚拟环境并安装依赖：

```sh
python -m venv .venv
```

使用当前终端对应的虚拟环境激活方式后，再安装依赖并执行后续 Python 命令：

```sh
python -m pip install -r requirements.txt
```

复制 [config.example.json](../config.example.json) 为 `config.local.json`，修改数据库连接和密钥。PowerShell 示例：

```powershell
Copy-Item config.example.json config.local.json
```

主要配置项如下：

| 配置项 | 用途 |
| --- | --- |
| `SQLALCHEMY_DATABASE_URI` | 部署者自己的 MySQL 连接 |
| `SECRET_KEY`、`JWT_SECRET_KEY` | 分别配置随机且独立的应用与令牌签名密钥 |
| `STORAGE_ROOT` | 常规文件存储目录 |
| `SPECIAL_STORAGE_USERNAME`、`SPECIAL_STORAGE_ROOT` | 特殊超级管理员项目的存储规则 |
| `FRONTEND_ORIGIN` | 网页客户端的实际来源地址 |
| `AUTH_SESSION_DAYS` | 设备会话有效期 |
| `INFOCENTER_API_BASE`、`INFOCENTER_API_TOKEN` | 可选信息中心的上游连接 |
| `MESSAGE_BRIDGE_*`、`WECHAT_FILES_*` | 可选桥接与附件来源配置 |

示例配置中的密钥和连接参数需要自行填写；两个签名密钥分别使用至少 32 字符的随机值，应用拒绝空值和 `REPLACE_` 占位符。可通过 `NETDISK_CONFIG` 指定仓库外的配置文件。数据库应预先创建，并使用支持 Unicode 的字符集。应用已有迁移文件，初始化或升级数据库时执行：

```sh
flask --app app db upgrade
```

本地开发启动：

```sh
flask --app app run --host 127.0.0.1 --port 5005
```

首次部署按初始化接口或网页初始化界面创建管理员，再登录使用。已有部署直接运行迁移，不重复初始化管理员。

生产部署应使用合适的 WSGI 服务与 HTTPS 反向代理，按照自己的环境调整 [deploy/](../deploy/) 模板中的工作目录、执行账号、解释器和服务端口。

## 网页客户端

安装两个网页子项目依赖，确保集成源码所需依赖可用：

```sh
npm ci --prefix integrations/DCP_InfoCenter
npm ci --prefix frontend/NetDisk-Frontend
npm run dev --prefix frontend/NetDisk-Frontend
```

主客户端开发端口为 `5105`，API 开发代理连接本地 `5005` 端口。修改站点来源、代理或部署端口后，应同时核对后端 `FRONTEND_ORIGIN`。

构建主客户端：

```sh
npm run build --prefix frontend/NetDisk-Frontend
```

## 可选信息中心

在 [integrations/DCP_InfoCenter/](../integrations/DCP_InfoCenter/) 下，将 `.env.example` 复制为 `.env.local`，配置自己的上游接口、令牌和网关来源。令牌仅由本地网关使用，不应设置成浏览器可公开的 `VITE_` 变量。

在该子项目目录中执行：

```sh
npm ci
npm run build
npm start
```

开发客户端可使用 `npm run dev`。网关、服务端适配、采集数据库和附件目录按启用的功能配置；安装客户端不会自动创建上游采集数据。

后台桥接与文件同步命令可以通过以下命令查看：

```sh
flask --app app --help
```

启用定时任务前，先在独立测试环境验证来源、访问权限和输出位置，再按 [deploy/](../deploy/) 模板配置。

## Android 构建与连接

项目位于 [mobile/DCP_Terminal/](../mobile/DCP_Terminal/)。客户端默认地址 `https://disk.example.invalid` 是占位地址，在网盘设置中改为自己的 HTTPS 站点。

设置 `ANDROID_HOME` 指向已安装的 Android SDK，将 `DCP_TERMINAL_SIGNING_KEY` 指向仓库外的签名文件。通过以下 PowerShell 脚本构建：

```powershell
.\mobile\DCP_Terminal\scripts\build.ps1 -AndroidSdk $env:ANDROID_HOME -SigningKey $env:DCP_TERMINAL_SIGNING_KEY
```

脚本构建应用与 instrumentation 测试包，执行 Lint 和独立数据测试，并将交付 APK 写入 `mobile/DCP_Terminal/release/`。需要第二处交付时设置 `DCP_APK_DELIVERY_DIR`；该配置为可选项，复制后校验 SHA-256 一致。签名文件和交付目录由部署者管理。

已有安装的覆盖升级需要使用兼容的签名。源码仓库不提供历史签名文件和原部署 APK。

## 后端与网页测试

在仓库根目录执行后端回归：

```sh
python -m unittest discover -s tests -p "test_*.py"
```

主网页的状态与会话测试：

```sh
node --test frontend/NetDisk-Frontend/tests/auth-session.test.mjs frontend/NetDisk-Frontend/tests/infocenter-state.test.mjs
```

信息中心服务端适配测试，在 `integrations/DCP_InfoCenter/server/` 下执行：

```sh
python -m unittest test_desktop test_timetable test_no_thinking
```

需要浏览器自动化时，在信息中心子项目中安装 Playwright 浏览器，再按该项目的 UI 检查脚本提供测试服务：

```sh
npx playwright install chromium
npm run test:ui
```

浏览器与真实接口验收依赖自己的测试服务及临时数据，应与日常使用的数据分开。

## Android 设备测试

构建测试包后，通过 `adb devices` 选择独立模拟器，将其序列号设置为 `DCP_ANDROID_TEST_SERIAL`：

```powershell
.\mobile\DCP_Terminal\scripts\test-android.ps1 -Serial $env:DCP_ANDROID_TEST_SERIAL -AndroidSdk $env:ANDROID_HOME
```

测试会替换客户端测试状态，因此使用独立模拟器。部分真实接口专项需要仓库外的临时账号 fixture；参考 [test-remote.ps1](../mobile/DCP_Terminal/scripts/test-remote.ps1) 和 [androidTest/](../mobile/DCP_Terminal/app/src/androidTest/) 中的测试入口。

历史 APK 不随源码仓库提供；升级专项需要自行保留具有兼容签名的旧版测试包。专项结束后清理临时账号、文件和设备状态。

## 开发检查

修改权限、会话、存储或消息行为时运行相关回归；调整前端或 Android 时执行对应构建。涉及设备点击、输入、媒体退出或窗口焦点的变化，应同时验证实际输入路径，不能只调用内部导航或关闭方法代替用户操作。
