# MultiAgentFramework-A2A-T

A2A-T多智能体框架开源项目

## 交付形式
1. 首次开源仅交付源码（托管在github），不提供安装包，交付内容不包括构建工程

## 功能说明
1. 本项目提供Agent注册中心模块供客户系统集成，用于管理客户系统内部Agent，提供Agent注册、Agent查询能力。
2. 默认所注册的Agent会作为公共资源，暂无Agent所有者设计。
3. 本项目仅用作功能模块，非完整系统，模块自身不提供登录认证、鉴权、用户管理、日志审计、加解密、证书管理、密钥管理、数据库等能力，需由客户系统提供如上安全基础设施；源码中已预留相关方法函数，供二次定制实现。
4. 本项目对注册的AgentCard信息默认使用文件存储：data/agentcard.json，暂未提供删除更新接口，如需修改需要操作文件并重服务启生效。
5. ![img.png](集成交互关系.png)

## 设计约束
1. 本项目需要运行在linux系统上，支持ipv4环境
2. 当前支持单实例部署，仅用于内部系统，不可开放到公网，不可作为云服务部署，否则目标系统需同步提供防火墙、提供web服务器实现认证鉴权等安全能力
3. 向本项目注册的AgentCard不可含有个人数据例如电话号码，不可含有敏感信息例如密码、凭据，否则有信息泄露风险

## 构建部署要求
本项目当前仅交付源码，使用方需完成构建及部署安装，需保证安装完成后，环境上的各个文件及目录权限最小，例如文件权限400、目录权限700、可执行.sh文件权限500。
项目中仅{安装目录}/etc/conf/log_config.conf、{安装目录}/etc/conf/server.conf两个文件需要可写权限，其他文件均只需要只读权限。

## 启动前配置
### ip端口配置（可选）
本项目默认是在回环地址127.0.0.1:5000上开放端口侦听，接收restful请求。可按照实际需要，修改此ip、端口配置。
配置文件：{安装目录}/etc/conf/server.conf
默认配置如下，可按需修改：
ip=127.0.0.1 
port=5000

### 证书配置（必选）
目标系统需提供一套完整证书用于启动端口，后续接收REST请求时会建立TLS传输通道，并根据配置校验对端证书。
配置文件：{安装目录}/etc/conf/server.conf
默认配置如下，可按需修改：
ssl_certfile=etc/ssl/service/server.cer
ssl_keyfile=etc/ssl/service/server_key.pem
ssl_keyfile_password=etc/ssl/service/cert_pwd
ssl_ca_certs=etc/ssl/service/trust.cer
ssl_crl_file=etc/ssl/service/revocationlist.crl
ssl_verify_client=true

证书要求：
server.cer：必选，身份证书，仅支持pem编码格式
 证书格式：X.509v3
 证书密钥算法、密钥长度：RSA(≥3072 bits)，ECDSA(≥256 bits)
 有效期：当前时间有效

cert_pwd：必选，私钥口令，文件名固定无后缀
 内容要求为密文
 口令原始明文复杂度需满足要求：至少8个字符，至少包含两种字符（数字、大写字母、小写字母、特殊字符`~!@# $%^& *()-_=+ |[{}];:'",<.>/? 和空格）
 口令原始明文需与server_key.pem匹配

server_key.pem：必选，私钥文件，仅支持pem编码格式
 私钥与公钥的匹配性：需要与server.cer中的公钥是匹配的

trust.cer：默认必选，Agent注册方的信任证书，仅支持pem编码格式，仅支持.cer文件，文件名固定，如果涉及多本证书，需合成一本
 启动配置项ssl_verify_client=true时，必须存在
 校验证书格式：X.509v3
 校验有效期：当前时间有效
 密钥算法、长度：RSA(≥3072 bits)，ECDSA(≥256 bits)

revocationlist.crl：可选，吊销列表，仅支持pem编码格式，仅支持.crl文件，如果涉及多本证书，需合成一本，可以不存在
 校验证书格式：X.509v2
 校验有效期：当前时间有效
不支持国密证书

注意：
1. 证书校验失败，将导致进程拉起失败。
2. 证书文件权限要求： 客户配置修改证书路径后，需保证证书文件及所在目录的权限最小化（例如文件权限400、目录权限700），同时需确保本项目进程拥有对文件的读取权限
3. 证书变更后，需重启进程生效

本项目仅读取使用这些证书，不提供证书管理能力，例如证书过期告警、备份恢复等。


## 🚀 启动项目

请按照以下步骤启动项目：

1. **进入项目目录下的 `bin` 文件夹**  
   ```bash
   cd /yourPath/agent-registry/bin
   ```

2. **创建并激活虚拟环境**  
  先创建一个项目所需的虚拟环境，（python版本要求>=3.10）比如：使用 `conda` 创建名为 `agent_registry` 的虚拟环境（如尚未创建）：
   ```bash
   conda create -n agent_registry python=3.1x
   ```
   激活虚拟环境：
   ```bash
   conda activate agent_registry
   ```

3. **安装依赖包**  
   安装项目所需的 Python 依赖：
   ```bash
   pip install -r ../requirements.txt
   ```

4. **启动项目**  
   执行启动脚本以运行项目：
   ```bash
   ./start.sh
   ```
   建议不要以root用户启动本项目，以避免本项目进程权限过大，被利用于权限提升攻击。以root用户运行时，此bash脚本将进行风险提示。
   备注：启动服务，请在系统集成时使用系统的框架操作，记录相应日志。`start.sh`只为了单机调试而用。

5. **审计日志**
   本项目默认为关键操作记录审计日志：
   日志路径：{安装目录}/log/audit/audit.log
   日志配置：{安装目录}/etc/conf/log_config.conf，可配置文件个数及文件大小，默认配置如下：
   audit_log_max_file_size_mb=1
   audit_log_backup_count=4
   默认支持4个历史日志文件：audit.log.1、audit.log.2、audit.log.3、audit.log.4，尾缀数字越大，代表日志越老，最新的日志规定记录在audit.log文件中。
   每个日志文件大小默认5M。

6. **运行日志**


## 停止服务

### 说明
`stop.sh` 是一个用于停止agent-registry注册中心服务的 Bash 脚本。它通过查找并终止名称为`agent_registry.start`(与启动的进程名对应)的进程来实现服务的停止。
备注：停止服务，请在系统集成时使用系统的框架操作，记录相应日志。`stop.sh`只为了单机调试而用。

### 基本用法

1. **进入项目目录下的 `bin` 文件夹**  
   ```bash
   cd /yourPath/agent-registry/bin
   ```

2. **执行脚本文件** 
    ```bash
    ./stop.sh
    ```
配置

PROCESS_NAME="agent_registry.start"

依赖项

pgrep：脚本依赖于 pgrep 命令来查找进程。大多数 Linux 系统默认安装了 pgrep。

功能说明

进程查找：使用 pgrep -f 查找与指定名称匹配的进程。

进程终止：首先尝试使用 kill 终止进程，如果进程未响应，则使用 kill -9 强制终止。

结果验证：脚本会验证进程是否已停止，并输出相应的结果信息。

输出信息

成功停止服务：输出 服务已停止。

未找到进程：输出 未找到运行中的服务。

强制停止进程：如果进程未响应，输出 进程未响应，强制停止...。

注意事项
确保脚本具有执行权限。如果没有，可以通过以下命令添加：

chmod +x stop.sh

如果脚本需要强制终止进程，可能需要管理员权限。

示例

假设进程名称为 agent_registry.start，运行脚本：

./stop.sh

输出示例：

正在停止服务...

找到进程 PID: 1234

服务已停止

# 自定义实现接口使用说明

## 系统概述

系统允许用户为不同操作定义自定义实现，同时为常见操作提供默认实现。

## 主要特性

1. **抽象基类**：为所有处理器定义统一接口
2. **默认实现**：为常见操作提供内置处理器
3. **自定义扩展**：支持用户注册自定义处理器
4. **异步支持**：支持同步和异步操作处理

## 安装使用

该模块设计为Python项目的组成部分，直接包含在项目结构中即可使用。

## 使用方法

### 1. 默认处理器

系统内置以下默认处理器：

- `decrypt`：处理解密操作
- `audit`：处理审计日志
- `authenticate`：处理认证
- `insert`：处理数据插入(异步)
- `query`：处理数据查询

### 2. 自定义处理器

创建并注册自定义处理器：

```python
from custom_handle import BaseHandler, HandlerRegistry, InterfaceType

class MyCustomHandler(BaseHandler):
    def handle(self, *args, **kwargs):
        # 自定义实现
        return "自定义结果"

# 注册自定义处理器
HandlerRegistry.register(InterfaceType.QUERY, MyCustomHandler)
```

### 3. 使用处理器
使用处理器(默认或自定义)：
```python
from custom_handle import HandlerRegistry, InterfaceType

# 获取处理器实例
handler = HandlerRegistry.get_handler(InterfaceType.QUERY)

# 使用处理器
result = handler.handle(...)

# 对于异步处理器
async def main():
    async_handler = HandlerRegistry.get_handler(InterfaceType.INSERT)
    result = await async_handler.handle(...)
```
API参考
BaseHandler
所有处理器必须继承的抽象基类。

方法：

handle(*args, **kwargs)：需要子类实现的抽象方法
HandlerRegistry
处理器注册表。

方法：

register(interface_type, handler_class)：

interface_type：InterfaceType枚举值
handler_class：BaseHandler的子类
get_handler(interface_type)：

返回注册的处理器实例或默认实现
默认处理器
DecryptHandler
处理解密操作。

AuditHandler
处理审计日志。

AuthenticateHandler
处理认证。

InsertHandler
处理数据插入(异步操作)。

QueryHandler
处理数据查询。


# 注册中心