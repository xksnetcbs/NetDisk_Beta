生成日期：2026-10-12

文档概要：通用项目文档索引，说明系统用途、阅读顺序与各子项目的位置。

# 项目说明

DCP NetDisk 是一个自托管的项目协作系统，包含网盘、项目与任务管理、日程、站内消息，以及可选的信息中心集成。网页客户端使用 Vue，后端使用 Flask，Android 客户端提供原生网盘、消息、日程、课表和桌面组件。

## 阅读顺序

1. [架构与模块](architecture.md)：组件关系、存储选择、登录与消息数据流。
2. [安装、开发与验证](development.md)：配置、启动、构建和测试命令。
3. [隐私、配置与第三方依赖](privacy-and-dependencies.md)：本地私有文件、发布范围和依赖声明。

## 仓库目录

| 路径 | 内容 |
| --- | --- |
| [app/](../app/) | Flask 应用工厂、API、权限、存储、日程和消息服务 |
| [app.py](../app.py) | 后端启动入口 |
| [migrations/](../migrations/) | 数据库迁移 |
| [frontend/NetDisk-Frontend/](../frontend/NetDisk-Frontend/) | 主网页客户端 |
| [integrations/DCP_InfoCenter/](../integrations/DCP_InfoCenter/) | 信息中心客户端、网关和服务端适配代码 |
| [mobile/DCP_Terminal/](../mobile/DCP_Terminal/) | Android 应用、桌面组件、测试和构建脚本 |
| [deploy/](../deploy/) | 服务部署模板 |
| [tests/](../tests/) | 后端回归测试 |
| [doc/](./) | 通用项目文档 |

## 使用准备

运行核心网盘需要 Python、MySQL 和 Node.js。信息中心需要自行配置可访问的上游服务；Android 客户端需要 Android SDK 和可访问的 HTTPS 网盘站点。连接参数、账户和密钥由部署者配置，源码仓库使用示例配置。

日程与课表分开管理，课表不自动生成日程。信息中心、消息桥接和微信文件同步可以按需启用，不影响核心网盘独立运行。

## 文档整理记录

2026-10-12：依据模块入口、配置项和现有测试脚本整理上述文档，采用仓库相对链接和示例配置。公开说明不携带原部署记录、运行数据、账户资料或历史验收截图。
