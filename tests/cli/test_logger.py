"""
CLI框架日志系统测试

测试CLILogger的日志记录功能和日志级别控制。
"""

import pytest
import os
import tempfile
from pathlib import Path
from loguru import logger
from agent_registry.cli.logger import CLILogger, cli_logger


class TestCLILogger:
    """CLILogger基础测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test_cli.log")
        self.test_logger = CLILogger(
            log_file=self.log_file,
            level="DEBUG"
        )
    
    def teardown_method(self):
        """每个测试方法后的清理"""
        logger.remove()
        CLILogger._instance = None
        CLILogger._initialized = False
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)
    
    def test_singleton_pattern(self):
        """应为单例模式"""
        logger1 = CLILogger(log_file=self.log_file)
        logger2 = CLILogger(log_file=self.log_file)
        assert logger1 is logger2
    
    def test_log_file_created(self):
        """日志文件应被创建"""
        self.test_logger.info("test message")
        assert os.path.exists(self.log_file)
    
    def test_info_log(self):
        """INFO日志应写入文件"""
        self.test_logger.info("test info message")
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "INFO" in content
        assert "test info message" in content
    
    def test_debug_log(self):
        """DEBUG日志应写入文件（级别设为DEBUG）"""
        self.test_logger.debug("test debug message")
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "DEBUG" in content
        assert "test debug message" in content
    
    def test_warning_log(self):
        """WARNING日志应写入文件"""
        self.test_logger.warning("test warning message")
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "WARNING" in content
        assert "test warning message" in content
    
    def test_error_log(self):
        """ERROR日志应写入文件"""
        self.test_logger.error("test error message")
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "ERROR" in content
        assert "test error message" in content
    
    def test_exception_log_with_trace(self):
        """EXCEPTION日志应包含堆栈信息"""
        try:
            raise ValueError("test exception")
        except ValueError as e:
            self.test_logger.exception("caught exception")
        
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "ERROR" in content
        assert "caught exception" in content
        assert "ValueError" in content


class TestCommandLogging:
    """命令审计日志测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test_cli.log")
        self.test_logger = CLILogger(
            log_file=self.log_file,
            level="DEBUG"
        )
    
    def teardown_method(self):
        """每个测试方法后的清理"""
        logger.remove()
        CLILogger._instance = None
        CLILogger._initialized = False
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)
    
    def test_log_command_start(self):
        """命令开始日志"""
        self.test_logger.log_command_start("agent list", {"org": "MyOrg"})
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "COMMAND_START" in content
        assert "agent list" in content
        assert "org" in content
    
    def test_log_command_start_empty_args(self):
        """命令开始日志（空参数）"""
        self.test_logger.log_command_start("start", {})
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "COMMAND_START" in content
        assert "args={}" in content
    
    def test_log_command_end_success(self):
        """命令结束日志（成功）"""
        self.test_logger.log_command_end("agent list", 0, 0.5)
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "COMMAND_END" in content
        assert "SUCCESS" in content
        assert "exit_code=0" in content
    
    def test_log_command_end_failed(self):
        """命令结束日志（失败）"""
        self.test_logger.log_command_end("agent query", 2, 0.3)
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "COMMAND_END" in content
        assert "FAILED" in content
        assert "exit_code=2" in content
    
    def test_log_command_error_without_trace(self):
        """命令错误日志（不含堆栈）"""
        error = ValueError("invalid argument")
        self.test_logger.log_command_error("agent query", error, include_trace=False)
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "COMMAND_ERROR" in content
        assert "ValueError" in content
        assert "invalid argument" in content
    
    def test_log_command_error_with_trace(self):
        """命令错误日志（含堆栈）"""
        try:
            raise ValueError("test error")
        except ValueError as e:
            self.test_logger.log_command_error("start", e, include_trace=True)
        
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "COMMAND_ERROR" in content
        assert "ValueError" in content


class TestLogLevelControl:
    """日志级别控制测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test_cli.log")
    
    def teardown_method(self):
        """每个测试方法后的清理"""
        logger.remove()
        CLILogger._instance = None
        CLILogger._initialized = False
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)
    
    def test_set_level_debug(self):
        """设置为DEBUG级别"""
        test_logger = CLILogger(log_file=self.log_file, level="DEBUG")
        test_logger.debug("debug message")
        test_logger.info("info message")
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "debug message" in content
        assert "info message" in content
    
    def test_set_level_info(self):
        """设置为INFO级别"""
        test_logger = CLILogger(log_file=self.log_file, level="INFO")
        test_logger.debug("debug message")
        test_logger.info("info message")
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "debug message" not in content
        assert "info message" in content
    
    def test_set_level_warning(self):
        """设置为WARNING级别"""
        test_logger = CLILogger(log_file=self.log_file, level="WARNING")
        test_logger.debug("debug message")
        test_logger.info("info message")
        test_logger.warning("warning message")
        test_logger.error("error message")
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "debug message" not in content
        assert "info message" not in content
        assert "warning message" in content
        assert "error message" in content
    
    def test_set_level_error(self):
        """设置为ERROR级别"""
        test_logger = CLILogger(log_file=self.log_file, level="ERROR")
        test_logger.info("info message")
        test_logger.warning("warning message")
        test_logger.error("error message")
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "info message" not in content
        assert "warning message" not in content
        assert "error message" in content
    
    def test_set_level_invalid(self):
        """设置无效级别应抛异常"""
        test_logger = CLILogger(log_file=self.log_file)
        with pytest.raises(ValueError):
            test_logger.set_level("INVALID")
    
    def test_dynamic_level_change(self):
        """动态切换日志级别"""
        test_logger = CLILogger(log_file=self.log_file, level="DEBUG")
        test_logger.debug("before change")
        
        test_logger.set_level("WARNING")
        test_logger.debug("after change should not appear")
        test_logger.warning("warning after change")
        
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "before change" in content
        assert "warning after change" in content
        assert "after change should not appear" not in content


class TestConsoleOutput:
    """控制台输出测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test_cli.log")
        self.test_logger = CLILogger(log_file=self.log_file)
    
    def teardown_method(self):
        """每个测试方法后的清理"""
        logger.remove()
        CLILogger._instance = None
        CLILogger._initialized = False
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)
    
    def test_enable_console_output(self):
        """启用控制台输出"""
        self.test_logger.enable_console_output()
        assert self.test_logger._console_handler_id is not None
    
    def test_disable_console_output(self):
        """禁用控制台输出"""
        self.test_logger.enable_console_output()
        self.test_logger.disable_console_output()
        assert self.test_logger._console_handler_id is None
    
    def test_console_output_idempotent(self):
        """多次启用控制台输出应为幂等"""
        self.test_logger.enable_console_output()
        first_id = self.test_logger._console_handler_id
        self.test_logger.enable_console_output()
        second_id = self.test_logger._console_handler_id
        assert first_id == second_id


class TestGlobalLogger:
    """全局cli_logger测试"""
    
    def test_global_logger_exists(self):
        """全局cli_logger应存在"""
        from agent_registry.cli.logger import cli_logger
        assert cli_logger is not None
        assert isinstance(cli_logger, CLILogger)
    
    def test_global_logger_is_singleton(self):
        """全局cli_logger应为单例"""
        from agent_registry.cli.logger import cli_logger as logger1
        from agent_registry.cli.logger import cli_logger as logger2
        assert logger1 is logger2
    
    def test_get_log_file_path(self):
        """获取日志文件路径"""
        path = cli_logger.get_log_file_path()
        assert isinstance(path, Path)
        assert path.name == "cli.log"
        assert "log" in str(path)


class TestArgsFormatting:
    """参数格式化测试"""
    
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test_cli.log")
        self.test_logger = CLILogger(log_file=self.log_file, level="DEBUG")
    
    def teardown_method(self):
        logger.remove()
        CLILogger._instance = None
        CLILogger._initialized = False
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)
    
    def test_private_args_filtered(self):
        """私有参数应被过滤"""
        self.test_logger.log_command_start("test", {
            "public_arg": "value",
            "_private_arg": "hidden",
            "_command": "should_not_show"
        })
        with open(self.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "public_arg" in content
        assert "_private_arg" not in content
        assert "_command" not in content