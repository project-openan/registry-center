# Agent Registry CLI 框架设计文档

## 一、概述

### 1.1 设计目标

为 Agent Registry 项目构建一个**轻量级、可扩展**的 CLI 框架，核心目标：

| 目标 | 说明 |
|------|------|
| 基本功能 | `-h` 帮助、`-v` 版本、`-x` 调试模式 |
| 扩展性 | 继承基类即可添加新命令，自动获得帮助支持 |
| 多级命令 | 支持 `cmd subcmd` 结构，如 `agent list`、`cert generate` |
| 错误处理 | 错误码 + 异常类型区分不同错误 |
| 易用性 | 开发者只需关注业务逻辑，框架处理基础设施 |

### 1.2 不涉及范围

- 具体业务命令实现（由其他开发者负责）
- `init` 配置初始化命令（已有专人负责）

### 1.3 日志系统设计

CLI 框架使用**独立的日志文件**，与项目基本日志分离：

| 日志类型 | 文件位置 | 用途 |
|----------|----------|------|
| 基本日志 | `log/server.log` | 服务运行日志（项目现有） |
| CLI日志 | `log/cli.log` | CLI命令执行日志（框架新增） |

**CLI日志记录内容**：
- 命令执行记录（命令名、参数、执行时间、退出码）
- 参数解析过程
- 错误和异常堆栈
- 命令审计信息

### 1.4 设计原则

```
┌────────────────────────────────────────────┐
│  框架职责                                  │
│  - 参数解析 (argparse)                     │
│  - 帮助生成 (-h/--help)                    │
│  - 命令路由                                │
│  - 错误处理与退出码                        │
│  - 调试模式 (-x/--debug)                   │
│  - 版本信息 (-v/--version)                 │
│  - CLI日志记录 (log/cli.log)               │
├────────────────────────────────────────────┤
│  开发者职责                                │
│  - 继承 BaseCommand                        │
│  - 实现 name/help/execute                  │
│  - 定义命令参数 (可选)                     │
│  - 业务逻辑                                │
└────────────────────────────────────────────┘
```

---

## 二、与业界CLI框架对比

### 2.1 主流框架概览

| 框架 | 维护方 | 特点 |
|------|--------|------|
| **argparse** | Python官方 | 标准库，基础功能 |
| **Click** | pallets团队 | 最流行，装饰器风格，Flask生态 |
| **Typer** | FastAPI作者 | 类型注解自动生成CLI |
| **Fire** | Google | 类方法自动识别为命令 |
| **Cliff** | OpenStack | 命令插件架构，生产级 |

### 2.2 核心特性对比

| 特性 | argparse | Click | Typer | Fire | Cliff | **本框架** |
|------|----------|-------|-------|------|-------|------------|
| 子命令支持 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 自动帮助生成 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 装饰器注册 | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |
| 命令类继承 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| 插件/自动发现 | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **错误码体系** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **日志系统集成** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **命令审计** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

### 2.3 本框架的独特优势

```
┌─────────────────────────────────────────────────────────────────┐
│                    本框架独特设计                                │
├─────────────────────────────────────────────────────────────────┤
│  1. 错误码体系                                                   │
│     - 6种异常类型携带退出码（2/3/4/5/127/130）                  │
│     - 业界其他框架无此设计                                       │
│     - 便于运维监控和自动化脚本判断                               │
├─────────────────────────────────────────────────────────────────┤
│  2. CLI专用日志系统                                              │
│     - loguru集成，独立日志文件（log/cli.log）                   │
│     - 与服务日志分离，便于问题排查                               │
│     - 业界其他框架无内置日志功能                                 │
├─────────────────────────────────────────────────────────────────┤
│  3. 命令审计                                                     │
│     - 自动记录：命令名、参数、执行时间、退出码                   │
│     - 支持事后分析和问题追溯                                     │
│     - 业界其他框架无此功能                                       │
├─────────────────────────────────────────────────────────────────┤
│  4. 层级隔离                                                     │
│     - 子命令在父命令作用域内有效                                 │
│     - 不同父命令可同名子命令                                     │
│     - 避免命名冲突                                               │
├─────────────────────────────────────────────────────────────────┤
│  5. 设计简洁                                                     │
│     - 继承BaseCommand + @CLI.register                           │
│     - 只需实现3个属性即可扩展命令                                │
│     - 学习曲线适中                                               │
└─────────────────────────────────────────────────────────────────┘
```

**设计风格定位**：

| 框架 | 命令定义方式 | 适用场景 |
|------|--------------|----------|
| Click | 函数 + 装饰器 | 通用CLI开发 |
| Typer | 函数 + 类型注解 | 快速开发 |
| Fire | 类方法自动识别 | 快速原型 |
| Cliff | 类继承 + 插件 | 企业级 |
| **本框架** | **类继承 + 装饰器注册** | **企业内部CLI + 需审计日志** |

---

## 三、框架核心特性

### 3.1 全局选项

| 选项 | 说明 | 示例 |
|------|------|------|
| `-h, --help` | 显示帮助信息 | `agent-registry -h` |
| `-v, --version` | 显示版本 | `agent-registry -v` |
| `-x, --debug` | 调试模式（详细日志） | `agent-registry -x start` |

### 3.2 命令层级

支持无限层级命令嵌套，采用**层级隔离**设计：

```
层级隔离原则：
┌─────────────────────────────────────────────────────────────┐
│  一级命令作用域：全局唯一                                    │
│  子命令作用域：只在父命令下有效，不同父命令可同名             │
└─────────────────────────────────────────────────────────────┘

示例：
agent-registry config set      # config 下的 set
agent-registry key set         # key 下的 set（另一个独立的 set）
agent-registry agent list      # agent 下的 list  
agent-registry cert list       # cert 下的 list（另一个独立的 list）

这两个 set 是完全不同的命令，互不影响。
```

**命令层级结构**：

```bash
# 一级命令
agent-registry start           # 一级命令：start
agent-registry stop            # 一级命令：stop

# 二级命令
agent-registry agent list      # agent(一级) -> list(二级)
agent-registry cert generate   # cert(一级) -> generate(二级)

# 三级命令
agent-registry config set key value   # config(一级) -> set(二级) -> key(三级参数)

# 每级都有独立帮助
agent-registry agent -h        # agent 命令组的帮助
agent-registry agent list -h   # list 子命令的帮助
```

**路由规则**：

```python
# 解析流程：
# 1. 解析第一个参数，匹配一级命令
# 2. 若一级命令有子命令，继续解析下一个参数
# 3. 在当前命令的 subcommands 中匹配
# 4. 重复步骤2-3直到没有子命令或参数耗尽

# 示例路由过程：
# agent-registry config set key value
# └─ 匹配一级命令 "config"
#    └─ 在 config.subcommands 中匹配 "set"
#       └─ set 无子命令，剩余参数 "key value" 作为 set 的参数
```

### 3.3 错误码规范

| 退出码 | 异常类型 | 说明 |
|--------|----------|------|
| 0 | - | 成功 |
| 1 | `CLIError` | 一般错误 |
| 2 | `ValidationError` | 参数校验错误 |
| 3 | `ConfigError` | 配置错误 |
| 4 | `ServiceError` | 服务错误 |
| 5 | `PermissionError` | 权限错误 |
| 127 | `CommandNotFoundError` | 命令不存在 |
| 130 | - | 用户中断 (Ctrl+C) |

### 3.4 调试模式

启用 `-x/--debug` 后：
- 输出详细执行日志
- 显示完整异常堆栈
- 打印参数解析结果
- 记录命令路由过程

---

## 四、架构设计

### 4.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     Entry Point (__main__.py)                │
│                      python -m agent_registry.cli            │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        CLI Engine                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │   Parser   │  │   Router   │  │   Runner   │             │
│  │  解析参数   │  │  路由命令   │  │  执行命令   │             │
│  └────────────┘  └────────────┘  └────────────┘             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │   Help     │  │   Error    │  │   Debug    │             │
│  │  帮助生成   │  │  错误处理   │  │  调试日志   │             │
│  └────────────┘  └────────────┘  └────────────┘             │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Command Registry                          │
│          层级结构存储，子命令在父命令作用域内隔离             │
│                                                              │
│  一级命令（全局唯一）:                                        │
│    "start": StartCommand                                     │
│    "stop": StopCommand                                       │
│    "agent": AgentCommand                                     │
│    "cert": CertCommand                                       │
│                                                              │
│  子命令（在父命令作用域内）：                                 │
│    agent.subcommands = {                                     │
│      "list": AgentListCommand,     # 只在 agent 下有效       │
│      "query": AgentQueryCommand    # 只在 agent 下有效       │
│    }                                                         │
│                                                              │
│    cert.subcommands = {                                      │
│      "list": CertListCommand,      # 只在 cert 下有效        │
│      "generate": CertGenCommand    # 只在 cert 下有效        │
│    }                                                         │
│                                                              │
│  注：agent.list 和 cert.list 是两个不同的命令                │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  BaseCommand (抽象基类)                      │
│                                                              │
│  @abstractmethod:                                            │
│  - name: str          # 命令名称                             │
│  - help_text: str     # 帮助描述                             │
│  - execute(args)      # 执行逻辑                             │
│                                                              │
│  @optional:                                                  │
│  - aliases: List[str] # 命令别名                             │
│  - subcommands: Dict  # 子命令                               │
│  - add_arguments(parser) # 添加参数                          │
│  - validate(args)     # 参数校验                             │
│  - handle_error(e)    # 错误处理                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Concrete Commands                          │
│           (由其他开发者继承 BaseCommand 实现)                │
│                                                              │
│  StartCommand, StopCommand, AgentCommand,                    │
│  CertCommand, ConfigCommand, KeyCommand, ...                 │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| CLI Engine | `cli/core.py` | 参数解析、命令路由、执行调度（parser 逻辑已集成在 core.py 中） |
| BaseCommand | `cli/base.py` | 抽象基类，定义命令接口 |
| Registry | `cli/registry.py` | 命令注册表，管理命令层级 |
| Exceptions | `cli/exceptions.py` | 定义 CLI 异常类型 |
| Context | `cli/context.py` | 运行时上下文（debug、config等） |
| Output | `cli/output.py` | 输出格式化 |
| Logger | `cli/logger.py` | CLI专用日志系统（集成loguru） |

### 4.3 目录结构

```
agent_registry/
├── cli/                    # CLI框架模块（新增）
│   ├── __init__.py         # 导出公共接口
│   ├── __main__.py         # 入口点
│   ├── core.py             # CLI引擎（含参数解析）
│   ├── base.py             # BaseCommand抽象基类
│   ├── registry.py         # 命令注册表
│   ├── exceptions.py       # 异常定义
│   ├── context.py          # 运行上下文
│   ├── output.py           # 输出格式化
│   ├── logger.py           # CLI日志系统（新增）
│   └── commands/           # 命令实现
│       ├── __init__.py
│       ├── agent.py        # Agent管理命令组
│       └── tag.py           # 标签管理命令组
└── ...                     # 现有模块
```

### 4.4 日志文件位置

```
log/
├── server.log              # 服务运行日志（项目现有）
├── cli.log                 # CLI命令执行日志（框架新增）
└── audit.log               # 审计日志（项目现有）
```

---

## 五、核心代码设计

### 5.1 BaseCommand 抽象基类

```python
# cli/base.py
from abc import ABC, abstractmethod
from argparse import ArgumentParser, Namespace
from typing import List, Dict, Optional


class BaseCommand(ABC):
    """
    CLI命令抽象基类
    
    所有命令必须继承此类。框架自动为每个命令生成帮助信息。
    
    示例:
        @CLI.register
        class StartCommand(BaseCommand):
            name = "start"
            help_text = "启动服务"
            
            def execute(self, args):
                print("Starting...")
                return 0
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        命令名称
        
        用于命令行调用，如 `agent-registry start` 中的 "start"
        """
        pass
    
    @property
    @abstractmethod
    def help_text(self) -> str:
        """
        帮助描述
        
        显示在 -h 帮助信息中
        """
        pass
    
    @property
    def aliases(self) -> List[str]:
        """
        命令别名
        
        如 ["run"] 使得 `agent-registry run` 等同于 `agent-registry start`
        """
        return []
    
    @property
    def subcommands(self) -> Dict[str, 'BaseCommand']:
        """
        子命令字典（层级隔离）
        
        子命令只在当前命令的作用域内有效，不同父命令可以有同名子命令。
        
        示例:
            # AgentCommand 的子命令
            class AgentCommand(BaseCommand):
                name = "agent"
                subcommands = {
                    "list": AgentListCommand(),   # 只在 agent 下有效
                    "query": AgentQueryCommand(),
                }
            
            # CertCommand 的子命令（可以有同名）
            class CertCommand(BaseCommand):
                name = "cert"
                subcommands = {
                    "list": CertListCommand(),    # 只在 cert 下有效
                    "generate": CertGenCommand(),
                }
            
            # agent.list 和 cert.list 是两个不同的命令
        
        注：子命令不需要 @CLI.register，只在父命令中实例化
        """
        return {}
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        添加命令专属参数
        
        Args:
            parser: argparse ArgumentParser
        """
        pass
    
    def validate(self, args: Namespace) -> Optional[str]:
        """
        参数校验
        
        在 execute 之前调用，返回错误信息或 None
        
        Args:
            args: 解析后的参数
            
        Returns:
            str: 错误信息，None 表示校验通过
        """
        return None
    
    @abstractmethod
    def execute(self, args: Namespace) -> int:
        """
        执行命令逻辑
        
        Args:
            args: 解析后的参数
            
        Returns:
            int: 退出码，0=成功，非0=失败
        """
        pass
    
    def handle_error(self, error: Exception, debug: bool = False) -> int:
        """
        错误处理
        
        execute 抛出异常时调用
        
        Args:
            error: 异常对象
            debug: 是否调试模式
            
        Returns:
            int: 退出码
        """
        if debug:
            import traceback
            traceback.print_exc()
        else:
            print(f"Error: {error}", file=sys.stderr)
        return 1
```

### 5.2 CLI Engine

```python
# cli/core.py
import sys
import argparse
import time
from typing import List, Optional, Dict, Type
from .base import BaseCommand
from .registry import CommandRegistry
from .exceptions import CLIError, CommandNotFoundError, ValidationError
from .context import Context
from .logger import cli_logger


class CLI:
    """
    CLI框架核心引擎
    """
    
    _instance = None
    _registry = CommandRegistry()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        self.name = "agent-registry"
        self.version = "1.0.0"
        self.description = "Agent Registry CLI"
    
    @classmethod
    def register(cls, command_class: Type[BaseCommand]) -> Type[BaseCommand]:
        """
        装饰器：注册命令
        
        Usage:
            @CLI.register
            class MyCommand(BaseCommand):
                ...
        """
        cls._registry.register(command_class)
        return command_class
    
    def run(self, argv: Optional[List[str]] = None) -> int:
        """
        运行CLI
        
        Args:
            argv: 命令行参数，None 时使用 sys.argv
            
        Returns:
            int: 退出码
        """
        argv = argv or sys.argv[1:]
        context = Context()
        
        # 解析全局选项
        argv, global_options = self._parse_global_options(argv)
        context.debug = global_options.get('debug', False)
        
        # 调试模式：设置日志级别为DEBUG
        if context.debug:
            cli_logger.set_level("DEBUG")
            cli_logger.debug(f"CLI started with args: {argv}")
        
        if global_options.get('version'):
            print(f"{self.name} v{self.version}")
            return 0
        
        # 构建解析器并解析命令
        parser = self._build_parser()
        
        try:
            args = parser.parse_args(argv)
        except SystemExit as e:
            # argparse 在 -h 或参数错误时抛出 SystemExit
            return e.code if isinstance(e.code, int) else 1
        
        # 无命令时显示主帮助
        if not hasattr(args, '_command') or args._command is None:
            parser.print_help()
            return 0
        
        # 获取命令实例
        command = args._command
        
        # 记录命令开始
        start_time = time.time()
        command_path = self._get_command_path(args)
        args_dict = {k: v for k, v in vars(args).items() if not k.startswith('_')}
        cli_logger.log_command_start(command_path, args_dict)
        
        # 调试模式：打印解析结果
        if context.debug:
            self._debug_print(args, command)
        
        # 执行命令
        exit_code = 0
        try:
            # 参数校验
            error = command.validate(args)
            if error:
                raise ValidationError(error)
            
            # 执行
            exit_code = command.execute(args)
        
        except CLIError as e:
            cli_logger.log_command_error(command_path, e, context.debug)
            self._handle_cli_error(e, context.debug)
            exit_code = e.exit_code
        
        except KeyboardInterrupt:
            cli_logger.warning(f"Command interrupted: {command_path}")
            print("\nInterrupted.", file=sys.stderr)
            exit_code = 130
        
        except Exception as e:
            cli_logger.log_command_error(command_path, e, context.debug)
            exit_code = command.handle_error(e, context.debug)
        
        finally:
            # 记录命令结束
            duration = time.time() - start_time
            cli_logger.log_command_end(command_path, exit_code, duration)
        
        return exit_code
    
    def _get_command_path(self, args) -> str:
        """
        获取命令完整路径
        
        如: "agent list", "cert generate"
        """
        parts = []
        if hasattr(args, '_command_name') and args._command_name:
            parts.append(args._command_name)
        
        # 递归查找子命令名称
        level = 0
        while hasattr(args, f'_subcommand_{level}'):
            subcmd = getattr(args, f'_subcommand_{level}')
            if subcmd:
                parts.append(subcmd)
            level += 1
        
        return ' '.join(parts) if parts else 'unknown'
    
    def _parse_global_options(self, argv: List[str]) -> tuple:
        """
        解析全局选项，从 argv 中提取
        
        Returns:
            (remaining_argv, global_options)
        """
        global_options = {}
        remaining = []
        
        i = 0
        while i < len(argv):
            arg = argv[i]
            
            if arg in ('-v', '--version'):
                global_options['version'] = True
            elif arg in ('-x', '--debug'):
                global_options['debug'] = True
            elif arg in ('-h', '--help'):
                remaining.append(arg)  # 交给 argparse 处理
            else:
                remaining.append(arg)
            
            i += 1
        
        return remaining, global_options
    
    def _build_parser(self) -> argparse.ArgumentParser:
        """
        构建 argparse 解析器
        """
        parser = argparse.ArgumentParser(
            prog=self.name,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            add_help=True
        )
        
        # 全局选项（帮助信息中显示）
        parser.add_argument('-v', '--version', action='store_true',
                           help='显示版本信息')
        parser.add_argument('-x', '--debug', action='store_true',
                           help='调试模式')
        
        # 子命令
        subparsers = parser.add_subparsers(
            dest='_command_name',
            title='commands',
            description='可用命令:',
            metavar='COMMAND'
        )
        
        # 递归添加所有命令
        for name, cmd_class in self._registry.get_all().items():
            self._add_command(subparsers, cmd_class())
        
        return parser
    
    def _add_command(self, subparsers, command: BaseCommand, level: int = 0):
        """
        递归添加命令及其子命令
        """
        # 创建命令解析器
        cmd_parser = subparsers.add_parser(
            command.name,
            help=command.help_text,
            aliases=command.aliases,
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        cmd_parser.set_defaults(_command=command)
        
        # 添加命令参数
        command.add_arguments(cmd_parser)
        
        # 处理子命令
        if command.subcommands:
            sub_subparsers = cmd_parser.add_subparsers(
                dest=f'_subcommand_{level}',
                title='subcommands',
                description='子命令:',
                metavar='SUBCOMMAND'
            )
            
            for sub_name, sub_cmd in command.subcommands.items():
                self._add_command(sub_subparsers, sub_cmd, level + 1)
    
    def _debug_print(self, args, command):
        """调试模式下打印详细信息"""
        print(f"[DEBUG] Command: {command.name}")
        print(f"[DEBUG] Args: {vars(args)}")
        print(f"[DEBUG] Help: {command.help_text}")
    
    def _handle_cli_error(self, error: CLIError, debug: bool):
        """处理 CLI 异常"""
        if debug:
            print(f"[DEBUG] Error type: {type(error).__name__}")
            print(f"[DEBUG] Exit code: {error.exit_code}")
        print(f"Error: {error.message}", file=sys.stderr)


def main():
    """CLI入口点"""
    cli = CLI()
    sys.exit(cli.run())
```

### 5.3 Command Registry

```python
# cli/registry.py
from typing import Dict, Type, Optional
from .base import BaseCommand
from .exceptions import CommandNotFoundError


class CommandRegistry:
    """
    命令注册表
    
    采用层级隔离设计：
    - 一级命令：全局唯一，注册时检查冲突
    - 子命令：在父命令的 subcommands 属性中定义，只在父命令作用域内有效
    
    示例：
        # 一级命令注册（全局唯一）
        @CLI.register
        class AgentCommand(BaseCommand):
            name = "agent"
            subcommands = {
                "list": AgentListCommand(),   # 只在 agent 下有效
                "query": AgentQueryCommand(),
            }
        
        @CLI.register  
        class CertCommand(BaseCommand):
            name = "cert"
            subcommands = {
                "list": CertListCommand(),    # 只在 cert 下有效（与 agent.list 不同）
                "generate": CertGenCommand(),
            }
        
        # agent.list 和 cert.list 是两个不同的命令
    """
    
    def __init__(self):
        self._commands: Dict[str, Type[BaseCommand]] = {}
    
    def register(self, command_class: Type[BaseCommand]) -> None:
        """
        注册一级命令
        
        Args:
            command_class: 命令类
            
        Raises:
            ValueError: 一级命令名称已存在
        """
        instance = command_class()
        name = instance.name
        
        # 一级命令必须全局唯一
        if name in self._commands:
            raise ValueError(
                f"一级命令 '{name}' 已存在。"
                f"子命令请在父命令的 subcommands 属性中定义。"
            )
        
        self._commands[name] = command_class
    
    def get(self, name: str) -> Optional[Type[BaseCommand]]:
        """
        获取一级命令类
        
        Args:
            name: 命令名称
            
        Returns:
            命令类或 None
        """
        return self._commands.get(name)
    
    def get_all(self) -> Dict[str, Type[BaseCommand]]:
        """
        获取所有一级命令
        
        Returns:
            一级命令字典
        """
        return self._commands.copy()
    
    def has(self, name: str) -> bool:
        """
        检查一级命令是否存在
        
        Args:
            name: 命令名称
            
        Returns:
            bool
        """
        return name in self._commands
    
    def clear(self) -> None:
        """清空注册表（用于测试）"""
        self._commands.clear()


class SubcommandResolver:
    """
    子命令解析器
    
    在父命令作用域内解析子命令，实现层级隔离
    """
    
    @staticmethod
    def resolve(parent: BaseCommand, subcommand_name: str) -> Optional[BaseCommand]:
        """
        在父命令作用域内解析子命令
        
        Args:
            parent: 父命令实例
            subcommand_name: 子命令名称
            
        Returns:
            子命令实例或 None
        """
        subcommands = parent.subcommands
        return subcommands.get(subcommand_name)
    
    @staticmethod
    def has_subcommand(parent: BaseCommand, name: str) -> bool:
        """
        检查父命令是否有指定子命令
        
        Args:
            parent: 父命令实例
            name: 子命令名称
            
        Returns:
            bool
        """
        return name in parent.subcommands
        name = instance.name
        
        if name in self._commands:
            raise ValueError(f"Command '{name}' already registered")
        
        self._commands[name] = command_class
    
    def get(self, name: str) -> Optional[Type[BaseCommand]]:
        """获取命令类"""
        return self._commands.get(name)
    
    def get_all(self) -> Dict[str, Type[BaseCommand]]:
        """获取所有一级命令"""
        return self._commands.copy()
    
    def has(self, name: str) -> bool:
        """检查命令是否存在"""
        return name in self._commands
    
    def clear(self) -> None:
        """清空注册表（用于测试）"""
        self._commands.clear()
```

### 5.4 Exceptions

```python
# cli/exceptions.py


class CLIError(Exception):
    """
    CLI异常基类
    
    所有CLI异常继承此类，携带退出码
    """
    
    def __init__(self, message: str, exit_code: int = 1):
        self.message = message
        self.exit_code = exit_code
        super().__init__(message)


class CommandNotFoundError(CLIError):
    """命令不存在"""
    
    def __init__(self, command: str):
        super().__init__(f"Command not found: '{command}'", exit_code=127)


class ValidationError(CLIError):
    """参数校验错误"""
    
    def __init__(self, message: str):
        super().__init__(message, exit_code=2)


class ConfigError(CLIError):
    """配置错误"""
    
    def __init__(self, message: str):
        super().__init__(message, exit_code=3)


class ServiceError(CLIError):
    """服务错误"""
    
    def __init__(self, message: str):
        super().__init__(message, exit_code=4)


class PermissionError(CLIError):
    """权限错误"""
    
    def __init__(self, message: str):
        super().__init__(message, exit_code=5)


class ArgumentMissingError(CLIError):
    """参数缺失"""
    
    def __init__(self, argument: str):
        super().__init__(f"Missing required argument: '{argument}'", exit_code=2)
```

### 5.5 CLI Logger（日志系统）

```python
# cli/logger.py
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from loguru import logger


class CLILogger:
    """
    CLI专用日志系统
    
    与项目基本日志分离，独立写入 log/cli.log
    
    使用方式:
        from agent_registry.cli.logger import cli_logger
        
        cli_logger.info("Command executed: start")
        cli_logger.error("Failed to start service")
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, log_file: str = "log/cli.log", level: str = "INFO"):
        if self._initialized:
            return
        
        self.log_file = log_file
        self.level = level
        self._setup_logger()
        self._initialized = True
    
    def _setup_logger(self):
        """
        配置loguru logger
        
        - 独立的日志文件：log/cli.log
        - 不影响项目现有的server.log
        - 支持日志级别控制
        """
        # 确保日志目录存在
        log_dir = Path(self.log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 移除loguru默认handler（避免输出到server.log）
        logger.remove()
        
        # 添加CLI专用handler
        logger.add(
            self.log_file,
            level=self.level,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
            rotation="10 MB",           # 日志文件最大10MB
            retention="7 days",         # 保留7天
            compression="zip",          # 压缩旧日志
            encoding="utf-8",
            filter=lambda record: record["extra"].get("cli", True)
        )
        
        # 调试模式下同时输出到控制台
        if os.environ.get("CLI_DEBUG") == "1":
            logger.add(
                sys.stderr,
                level="DEBUG",
                format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
                colorize=True
            )
    
    def log_command_start(self, command: str, args: dict):
        """
        记录命令开始执行
        
        Args:
            command: 命令名称
            args: 命令参数
        """
        logger.bind(cli=True).info(
            f"COMMAND_START | {command} | args={args}"
        )
    
    def log_command_end(self, command: str, exit_code: int, duration: float):
        """
        记录命令执行结束
        
        Args:
            command: 命令名称
            exit_code: 退出码
            duration: 执行时长（秒）
        """
        status = "SUCCESS" if exit_code == 0 else "FAILED"
        logger.bind(cli=True).info(
            f"COMMAND_END | {command} | {status} | exit_code={exit_code} | duration={duration:.3f}s"
        )
    
    def log_command_error(self, command: str, error: Exception, debug: bool = False):
        """
        记录命令执行错误
        
        Args:
            command: 命令名称
            error: 异常对象
            debug: 是否调试模式
        """
        if debug:
            logger.bind(cli=True).exception(
                f"COMMAND_ERROR | {command} | {type(error).__name__}: {error}"
            )
        else:
            logger.bind(cli=True).error(
                f"COMMAND_ERROR | {command} | {type(error).__name__}: {error}"
            )
    
    def debug(self, message: str):
        """调试日志"""
        logger.bind(cli=True).debug(message)
    
    def info(self, message: str):
        """信息日志"""
        logger.bind(cli=True).info(message)
    
    def warning(self, message: str):
        """警告日志"""
        logger.bind(cli=True).warning(message)
    
    def error(self, message: str):
        """错误日志"""
        logger.bind(cli=True).error(message)
    
    def exception(self, message: str):
        """异常日志（包含堆栈）"""
        logger.bind(cli=True).exception(message)
    
    def set_level(self, level: str):
        """
        动态设置日志级别
        
        Args:
            level: DEBUG/INFO/WARNING/ERROR
        """
        self.level = level
        # 重新配置logger
        logger.remove()
        self._setup_logger()


# 全局CLI日志实例
cli_logger = CLILogger()
```

**日志格式示例**：

```log
# log/cli.log 内容示例
2026-04-22 10:30:15.123 | INFO     | COMMAND_START | start | args={'port': 5000, 'daemon': False}
2026-04-22 10:30:15.456 | INFO     | COMMAND_END | start | SUCCESS | exit_code=0 | duration=0.333s
2026-04-22 10:31:20.789 | INFO     | COMMAND_START | agent list | args={'org': 'MyOrg', 'limit': 50}
2026-04-22 10:31:21.012 | ERROR    | COMMAND_ERROR | agent list | ConnectionError: Service unavailable
2026-04-22 10:31:21.015 | INFO     | COMMAND_END | agent list | FAILED | exit_code=4 | duration=0.223s
```

### 5.6 Context

```python
# cli/context.py
from typing import Optional
from pathlib import Path


class Context:
    """
    CLI运行上下文
    
    存储全局状态：调试模式、配置路径等
    """
    
    def __init__(self):
        self.debug: bool = False
        self.config_file: Optional[str] = None
        self.output_format: str = 'text'
    
    @classmethod
    def from_args(cls, args) -> 'Context':
        """从解析后的参数创建上下文"""
        ctx = cls()
        ctx.debug = getattr(args, 'debug', False)
        ctx.config_file = getattr(args, 'config', None)
        ctx.output_format = getattr(args, 'output', 'text')
        return ctx
```

### 5.7 Output

```python
# cli/output.py
import json
import sys
from typing import Any


class Output:
    """
    输出格式化
    
    支持 text/json/table 格式
    """
    
    def __init__(self, format: str = 'text'):
        self.format = format
    
    def print(self, data: Any, title: str = None):
        """格式化输出"""
        if self.format == 'json':
            self._print_json(data)
        elif self.format == 'table':
            self._print_table(data, title)
        else:
            self._print_text(data, title)
    
    def _print_json(self, data: Any):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    
    def _print_table(self, data: Any, title: str = None):
        """表格输出（需要 tabulate 库）"""
        try:
            from tabulate import tabulate
            if isinstance(data, list) and data and isinstance(data[0], dict):
                headers = list(data[0].keys())
                rows = [[item.get(h, '') for h in headers] for item in data]
                print(tabulate(rows, headers=headers, tablefmt='grid'))
            else:
                print(data)
        except ImportError:
            self._print_text(data, title)
    
    def _print_text(self, data: Any, title: str = None):
        """文本输出"""
        if title:
            print(f"\n{title}")
            print('=' * len(title))
        
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"{k}: {v}")
        elif isinstance(data, list):
            for item in data:
                print(item)
        else:
            print(data)
    
    def success(self, msg: str):
        """成功消息"""
        print(f"✓ {msg}")
    
    def error(self, msg: str):
        """错误消息"""
        print(f"✗ {msg}", file=sys.stderr)
    
    def debug(self, msg: str):
        """调试消息"""
        print(f"[DEBUG] {msg}")
```

### 5.8 Entry Point

```python
# cli/__main__.py
import sys
from .core import CLI, main


# 自动发现并导入命令模块
def _auto_discover_commands():
    """
    自动发现 cli/commands/ 目录下的命令模块
    """
    import os
    from pathlib import Path
    
    commands_dir = Path(__file__).parent / 'commands'
    if commands_dir.exists():
        for file in commands_dir.glob('*.py'):
            if file.name.startswith('_'):
                continue
            module_name = file.stem
            __import__(f'{__package__}.commands.{module_name}')


# 执行自动发现
_auto_discover_commands()


if __name__ == '__main__':
    main()
```

### 5.9 Package Init

```python
# cli/__init__.py
from .core import CLI
from .base import BaseCommand
from .exceptions import (
    CLIError,
    CommandNotFoundError,
    ValidationError,
    ConfigError,
    ServiceError,
    PermissionError,
    ArgumentMissingError
)
from .context import Context
from .output import Output
from .logger import cli_logger, CLILogger


__all__ = [
    'CLI',
    'BaseCommand',
    'CLIError',
    'CommandNotFoundError',
    'ValidationError',
    'ConfigError',
    'ServiceError',
    'PermissionError',
    'ArgumentMissingError',
    'Context',
    'Output',
    'cli_logger',
    'CLILogger',
]
```

---

## 六、命令分类建议

> **注**：以下为设计阶段的命令规划建议。当前版本实现中，仅 `agent` 和 `tag` 两大类命令可用，其余（`start`/`stop`/`restart`/`status`、`config`、`cert`、`key`）尚未实现。

### 6.1 服务管理类（未实现）

| 命令 | 说明 | 预期参数 |
|------|------|----------|
| `start` | 启动服务 | `--daemon`, `--port`, `--config` |
| `stop` | 停止服务 | `--force` |
| `restart` | 重启服务 | - |
| `status` | 查看状态 | `-o json/table` |

### 6.2 配置管理类（未实现）

### 6.3 证书管理类（未实现）

### 6.4 公钥管理类（未实现）

| 命令 | 说明 | 预期参数 |
|------|------|----------|
| `key add` | 添加公钥 | `--org`, `--agent`, `--file` |
| `key remove` | 删除公钥 | `--org`, `--agent` |
| `key list` | 列出公钥 | `--org` |
| `key get` | 获取公钥 | `--org`, `--agent` |

### 6.5 Agent管理类

| 命令 | 说明 | 预期参数 |
|------|------|----------|
| `agent list` | 列出Agent | `--org`, `--limit` |
| `agent query` | 精确查询 | `--name`, `--org` |
| `agent get <name>` | 获取详情 | `--org` |
| `agent search` | 语义检索 | `<query>`, `--top-n` |

### 6.6 其他

| 命令 | 说明 | 预期参数 |
|------|------|----------|
| `version` | 版本信息 | - |

---

## 七、使用指南（面向开发者）

### 7.1 创建一级命令

```python
# cli/commands/start.py
from agent_registry.cli import BaseCommand, CLI
from argparse import ArgumentParser, Namespace


@CLI.register
class StartCommand(BaseCommand):
    """启动服务命令"""
    
    @property
    def name(self) -> str:
        return "start"
    
    @property
    def help_text(self) -> str:
        return "启动 Agent Registry 服务"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument('--daemon', '-d', action='store_true',
                           help='后台运行')
        parser.add_argument('--port', '-p', type=int,
                           help='监听端口')
        parser.add_argument('--config', '-c',
                           help='配置文件路径')
    
    def execute(self, args: Namespace) -> int:
        # 业务逻辑
        print(f"Starting service on port {args.port or 5000}...")
        return 0
```

**效果**：

```bash
agent-registry start -h
# 显示：
# usage: agent-registry start [-h] [--daemon] [--port PORT] [--config CONFIG]
# 
# 启动 Agent Registry 服务
# 
# options:
#   --daemon, -d    后台运行
#   --port, -p      监听端口
#   --config, -c    配置文件路径
#   -h, --help      显示帮助信息
```

### 7.2 创建多级命令

```python
# cli/commands/agent.py
from agent_registry.cli import BaseCommand, CLI
from argparse import ArgumentParser, Namespace
from typing import Dict


@CLI.register
class AgentCommand(BaseCommand):
    """Agent管理命令组"""
    
    @property
    def name(self) -> str:
        return "agent"
    
    @property
    def help_text(self) -> str:
        return "Agent 管理命令"
    
    @property
    def subcommands(self) -> Dict[str, BaseCommand]:
        return {
            "list": AgentListCommand(),
            "query": AgentQueryCommand(),
            "get": AgentGetCommand(),
        }


class AgentListCommand(BaseCommand):
    """列出Agent"""
    
    @property
    def name(self) -> str:
        return "list"
    
    @property
    def help_text(self) -> str:
        return "列出已注册的 Agent"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument('--org', '-o', help='按组织筛选')
        parser.add_argument('--limit', '-l', type=int, default=50)
    
    def execute(self, args: Namespace) -> int:
        print(f"Listing agents (limit={args.limit})...")
        return 0


class AgentQueryCommand(BaseCommand):
    """查询Agent"""
    
    @property
    def name(self) -> str:
        return "query"
    
    @property
    def help_text(self) -> str:
        return "精确查询 Agent"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument('--name', '-n', required=True, help='Agent名称')
        parser.add_argument('--org', '-o', required=True, help='组织名称')
    
    def execute(self, args: Namespace) -> int:
        print(f"Querying agent: {args.name} @ {args.org}")
        return 0


class AgentGetCommand(BaseCommand):
    """获取Agent详情"""
    
    @property
    def name(self) -> str:
        return "get"
    
    @property
    def help_text(self) -> str:
        return "获取 Agent 详情"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument('name', help='Agent名称')
        parser.add_argument('--org', '-o', required=True, help='组织名称')
    
    def execute(self, args: Namespace) -> int:
        print(f"Getting agent: {args.name} @ {args.org}")
        return 0
```

**效果**：

```bash
agent-registry agent -h
# 显示 agent 命令组的帮助

agent-registry agent list -h
# 显示 list 子命令的帮助

agent-registry agent query --name MyAgent --org MyOrg
# 执行查询
```

### 7.3 层级隔离说明

**核心原则**：
- 一级命令：全局唯一，注册时检查冲突
- 子命令：在父命令的 `subcommands` 属性中定义，只在父命令作用域内有效
- 不同父命令可以有同名子命令

```python
# 示例：两个不同的 list 子命令

# cli/commands/agent.py
@CLI.register
class AgentCommand(BaseCommand):
    name = "agent"
    
    @property
    def subcommands(self) -> Dict[str, BaseCommand]:
        return {
            "list": AgentListCommand(),  # agent 下的 list
        }

# cli/commands/cert.py  
@CLI.register
class CertCommand(BaseCommand):
    name = "cert"
    
    @property
    def subcommands(self) -> Dict[str, BaseCommand]:
        return {
            "list": CertListCommand(),   # cert 下的 list（不同的命令）
        }

# AgentListCommand 和 CertListCommand 是两个完全不同的命令类
# 它们只在各自的父命令作用域内有效
```

**路由过程**：

```bash
agent-registry agent list
# 1. 匹配一级命令 "agent"
# 2. 在 agent.subcommands 中查找 "list" → 找到 AgentListCommand
# 3. 执行 AgentListCommand

agent-registry cert list  
# 1. 匹配一级命令 "cert"
# 2. 在 cert.subcommands 中查找 "list" → 找到 CertListCommand
# 3. 执行 CertListCommand（与上面的 list 不同）

agent-registry list
# 错误！"list" 不是一级命令
```

**一级命令冲突检测**：

```python
# 错误示例：重复的一级命令
@CLI.register
class AgentCommand(BaseCommand):
    name = "agent"

@CLI.register  # 会抛出 ValueError
class AnotherAgentCommand(BaseCommand):
    name = "agent"  # 一级命令 "agent" 已存在

# 正确做法：使用子命令
@CLI.register
class AgentCommand(BaseCommand):
    name = "agent"
    subcommands = {
        "v2": AgentV2Command(),  # agent v2
    }
```

### 7.4 使用异常和错误码

```python
from agent_registry.cli import ValidationError, ConfigError, ServiceError


@CLI.register
class MyCommand(BaseCommand):
    # ...
    
    def execute(self, args: Namespace) -> int:
        # 参数校验错误
        if not args.required_field:
            raise ValidationError("Missing required field: --required-field")
        
        # 配置错误
        if not self._load_config(args.config):
            raise ConfigError(f"Config file not found: {args.config}")
        
        # 服务错误
        try:
            self._call_service()
        except ConnectionError as e:
            raise ServiceError(f"Service unavailable: {e}")
        
        return 0
```

### 7.5 调试模式使用

```bash
# 正常模式：简洁错误
agent-registry start --port invalid
# Error: invalid int value: 'invalid'

# 调试模式：详细堆栈
agent-registry -x start --port invalid
# [DEBUG] Command: start
# [DEBUG] Args: {'port': 'invalid', ...}
# [DEBUG] Error type: ValueError
# Traceback (most recent call last):
#   ...
# ValueError: invalid literal for int() with base 10: 'invalid'
```

---

## 八、框架配置

### 8.1 setup.py 入口点

```python
entry_points={
    "console_scripts": [
        "agent-registry=agent_registry.cli:main",
    ],
},
```

### 8.2 自动发现命令

框架自动扫描 `cli/commands/` 目录下的 `.py` 文件：

```
cli/commands/
├── start.py      → 自动注册 StartCommand
├── stop.py       → 自动注册 StopCommand
├── agent.py      → 自动注册 AgentCommand
├── cert.py       → 自动注册 CertCommand
└── ...
```

开发者只需在 `cli/commands/` 下创建文件并使用 `@CLI.register` 装饰器。

---

## 九、测试策略

### 9.1 框架单元测试

```python
# tests/cli/test_framework.py
import pytest
from agent_registry.cli import CLI, BaseCommand, ValidationError
from argparse import Namespace


class MockCommand(BaseCommand):
    @property
    def name(self):
        return "mock"
    
    @property
    def help_text(self):
        return "Mock command"
    
    def execute(self, args):
        return 0


class TestCLI:
    def test_version(self, capsys):
        cli = CLI()
        result = cli.run(['-v'])
        assert result == 0
        captured = capsys.readouterr()
        assert 'agent-registry' in captured.out
    
    def test_debug_mode(self, capsys):
        cli = CLI()
        cli.run(['-x', 'mock'])
        # 验证调试输出
    
    def test_help(self, capsys):
        cli = CLI()
        with pytest.raises(SystemExit):
            cli.run(['-h'])
    
    def test_unknown_command(self, capsys):
        cli = CLI()
        result = cli.run(['unknown'])
        assert result == 127  # CommandNotFoundError
    
    def test_validation_error(self, capsys):
        cmd = MockCommand()
        result = cmd.execute(Namespace())
        assert result == 0


class TestExceptions:
    def test_validation_error_code(self):
        e = ValidationError("test")
        assert e.exit_code == 2
    
    def test_config_error_code(self):
        e = ConfigError("test")
        assert e.exit_code == 3
    
    def test_command_not_found_code(self):
        e = CommandNotFoundError("test")
        assert e.exit_code == 127
```

---

## 十、CLI日志系统使用

### 10.1 日志文件

CLI框架使用独立的日志文件 `log/cli.log`，与项目基本日志分离：

| 日志类型 | 文件 | 内容 |
|----------|------|------|
| CLI日志 | `log/cli.log` | 命令执行记录、参数、错误堆栈 |
| 服务日志 | `log/server.log` | 服务运行日志（项目现有） |

### 10.2 日志级别

| 级别 | 说明 | 使用场景 |
|------|------|----------|
| DEBUG | 调试信息 | `-x/--debug` 模式下启用 |
| INFO | 正常信息 | 命令执行记录 |
| WARNING | 警告信息 | 用户中断、潜在问题 |
| ERROR | 错误信息 | 命令执行失败 |
| EXCEPTION | 异常堆栈 | 严重错误，包含完整堆栈 |

### 10.3 在命令中使用日志

```python
from agent_registry.cli import BaseCommand, CLI, cli_logger
from argparse import ArgumentParser, Namespace


@CLI.register
class MyCommand(BaseCommand):
    
    @property
    def name(self) -> str:
        return "mycommand"
    
    @property
    def help_text(self) -> str:
        return "我的命令"
    
    def execute(self, args: Namespace) -> int:
        # 记录业务日志
        cli_logger.info(f"Processing with option: {args.option}")
        
        try:
            result = self._do_something(args)
            cli_logger.info(f"Result: {result}")
            return 0
        except Exception as e:
            # 记录错误日志（包含堆栈）
            cli_logger.exception(f"Failed: {e}")
            return 1
```

### 10.4 日志输出示例

```log
# log/cli.log
2026-04-22 10:30:15.123 | INFO     | COMMAND_START | agent list | args={'org': 'MyOrg', 'limit': 50}
2026-04-22 10:30:15.456 | INFO     | Processing with option: verbose
2026-04-22 10:30:15.789 | INFO     | Result: 15 agents found
2026-04-22 10:30:16.012 | INFO     | COMMAND_END | agent list | SUCCESS | exit_code=0 | duration=0.889s

2026-04-22 10:31:20.123 | INFO     | COMMAND_START | cert generate | args={'type': 'server', 'output': 'etc/ssl/'}
2026-04-22 10:31:20.456 | ERROR    | COMMAND_ERROR | cert generate | PermissionError: Cannot write to etc/ssl/
2026-04-22 10:31:20.459 | INFO     | COMMAND_END | cert generate | FAILED | exit_code=5 | duration=0.336s

# 调试模式下的日志（-x/--debug）
2026-04-22 10:32:00.001 | DEBUG    | CLI started with args: ['agent', 'query']
2026-04-22 10:32:00.002 | DEBUG    | Parsing arguments...
2026-04-22 10:32:00.003 | DEBUG    | Command resolved: agent query
2026-04-22 10:32:00.004 | INFO     | COMMAND_START | agent query | args={'name': 'TestAgent', 'org': 'TestOrg'}
```

### 10.5 动态调整日志级别

**两种"级别"的区别**：

| 类型 | 说明 | 示例 |
|------|------|------|
| **日志方法级别** | 指定**这条日志**是什么级别 | `cli_logger.debug("msg")` 写一条 DEBUG 级日志 |
| **日志过滤级别** | 控制**哪些日志会被记录到文件** | `set_level("WARNING")` 只记录 WARNING 及以上 |

**级别优先级**：DEBUG < INFO < WARNING < ERROR

```python
from agent_registry.cli import cli_logger

# 设置过滤级别为 WARNING
cli_logger.set_level("WARNING")

cli_logger.debug("调试信息")    # ❌ 不写入文件（DEBUG < WARNING）
cli_logger.info("普通信息")     # ❌ 不写入文件（INFO < WARNING）
cli_logger.warning("警告信息")  # ✅ 写入文件
cli_logger.error("错误信息")    # ✅ 写入文件

# 设置过滤级别为 DEBUG（记录所有）
cli_logger.set_level("DEBUG")

cli_logger.debug("调试信息")    # ✅ 写入文件
cli_logger.info("普通信息")     # ✅ 写入文件
cli_logger.warning("警告信息")  # ✅ 写入文件
cli_logger.error("错误信息")    # ✅ 写入文件
```

**实际用途**：

| 场景 | 设置级别 | 效果 |
|------|----------|------|
| 生产环境 | `INFO` 或 `WARNING` | 减少日志量，只记录重要信息 |
| 调试问题 | `DEBUG` | 记录所有详细信息 |
| `-x/--debug` | 自动设为 `DEBUG` | 框架自动处理，无需手动调用 |

---

## 十一、框架特性总结

| 特性 | 实现方式 | 说明 |
|------|----------|------|
| `-h/--help` | argparse 自动生成 | 每级命令都有独立帮助 |
| `-v/--version` | 全局选项解析 | 显示框架版本 |
| `-x/--debug` | 全局选项解析 | 详细日志和堆栈 |
| 多级命令 | `subcommands` 属性递归 | 无限层级支持 |
| **层级隔离** | 子命令在父命令作用域内 | 不同父命令可同名子命令 |
| 错误码 | 异常类携带 `exit_code` | 6 种错误类型 |
| 命令注册 | `@CLI.register` 装饰器 | 声明式注册，一级命令全局唯一 |
| 自动发现 | 扫描 `commands/` 目录 | 无需手动导入 |
| CLI日志 | loguru + 独立文件 | `log/cli.log`，自动记录命令执行 |
| 扩展性 | 继承 `BaseCommand` | 只需实现 3 个属性 |

---

**文档版本**: 5.0  
**更新说明**: 
- 添加与业界CLI框架对比分析
- 添加CLI专用日志系统设计
- 添加层级隔离设计，解决多级命令命名冲突问题