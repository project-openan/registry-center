# MultiAgentFramework-A2A-T

A2A-T多智能体框架开源项目

本模块需要运行在linux系统上，支持ipv4环境

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

# 注册中心