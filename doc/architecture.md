生成日期：2026-10-12

文档概要：描述网页、后端、信息中心和 Android 客户端的模块关系，以及存储、会话与消息的边界。

# 架构与模块

## 组件关系

网页和 Android 客户端调用 Flask API。Flask 使用 MySQL 保存业务记录，将文件内容写入本地存储目录。信息中心适配层按配置连接独立的上游服务，桥接进程将可用消息与文件同步到系统。

| 组件 | 入口或目录 | 职责 |
| --- | --- | --- |
| Flask 后端 | [app/__init__.py](../app/__init__.py)、[app.py](../app.py) | 初始化数据库、认证、蓝图和命令 |
| 核心业务 API | [app/api.py](../app/api.py) | 账号、项目、任务、文件、日程和站内消息 |
| 业务模型与权限 | [app/models.py](../app/models.py)、[app/services.py](../app/services.py) | 关系数据、角色与访问控制 |
| 存储服务 | [app/storage.py](../app/storage.py)、[app/readable_storage.py](../app/readable_storage.py) | 存储位置选择及可读目录维护 |
| 设备会话 | [app/auth_sessions.py](../app/auth_sessions.py) | 设备登录会话、刷新与撤销 |
| 移动接口 | [app/mobile.py](../app/mobile.py) | 消息与日程快照、终端同步接口 |
| 信息中心适配 | [app/infocenter.py](../app/infocenter.py)、[integrations/DCP_InfoCenter/](../integrations/DCP_InfoCenter/) | 上游代理、会话与附件接口及客户端 |
| 消息桥接 | [app/message_bridge.py](../app/message_bridge.py)、[app/message_replies.py](../app/message_replies.py) | 消息来源映射、同步和受权限约束的回复 |
| 微信文件同步 | [app/wechat_files.py](../app/wechat_files.py) | 根据配置读取附件来源并同步文件 |
| 网页客户端 | [frontend/NetDisk-Frontend/src/](../frontend/NetDisk-Frontend/src/) | 项目协作、网盘、日程和消息界面 |
| Android 客户端 | [mobile/DCP_Terminal/app/src/](../mobile/DCP_Terminal/app/src/) | 原生网盘、预览、消息、课表、日程与桌面组件 |

## 数据与文件存储

MySQL 保存用户、项目、权限、任务、消息、日程和文件节点等记录。磁盘文件内容与文件节点分开管理；读写文件时仍由 API 校验节点权限，不向客户端公开宿主机文件路径。

`STORAGE_ROOT` 是常规文件存储根目录。特殊项目存储由两个配置项控制：

- `SPECIAL_STORAGE_USERNAME`：指定特殊存储规则关联的超级管理员，默认示例账号名为 `storage_admin`。
- `SPECIAL_STORAGE_ROOT`：这类项目的存储根目录，默认 `~/Net_Disk`，由运行服务的账号展开。

指定账号同时具有 `super_admin` 系统角色时，其创建或拥有的项目使用特殊存储根目录；其他项目保持常规存储规则。该规则选择物理存储位置，项目权限仍由系统角色和项目成员关系决定。

配置目录变化与已有文件迁移是不同操作。迁移已有部署前，应先备份数据库及文件，并检查当前存储命令的帮助和预演选项。

## 登录与设备状态

网页通过账号认证访问 API。Android 设备持久保存服务端设备登录会话，访问令牌保留在内存，重新打开应用时尝试恢复会话。退出、撤销或账号变化会清理相关缓存，并阻止旧账号的异步响应覆盖新账号状态。

所有客户端仍需通过服务端权限检查。设备自动登录依赖有效会话，不绕过账户状态、角色和项目成员权限。

## 日程与课表

网盘日程通过后端接口同步，Android 保存离线副本并提供桌面组件。课表使用独立的数据结构与同步接口，不自动混入日程列表；两类数据由各自界面管理。

## 消息与可选集成

站内消息保存可校验的来源标识。客户端显示会话历史，并根据当前来源和权限判断是否允许回复；消息文本、会话编号和来源标识共同约束回复目标。

信息中心可连接部署者已有的上游服务。消息桥接、附件同步和定时任务使用明确配置的数据源，运行数据不属于源代码。核心网盘可以在这些集成关闭的状态下独立启动。

## 文件预览生命周期

Android 使用独立预览界面显示文本、图片、PDF、音频与视频；Office 预览依赖服务端转换能力。视频退出时清理控制器、数据源和播放器，迟到的准备或错误回调受会话与关闭状态检查。预览、保存到设备和其他应用打开分别使用相应的文件接口。

不同设备对媒体编码格式的支持可能不同。服务端文件读取、客户端解码和外部转换工具应分别验证。
