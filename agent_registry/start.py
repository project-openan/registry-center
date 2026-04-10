# agent_registry/start.py
import asyncio
import os
import ssl
import sys

import uvicorn
from loguru import logger
from uvicorn import config

from agent_registry.cipher_converter import CipherConverter
from agent_registry.config import CONN_TIMEOUT, TLS_CIPHER, FORWARDED_ALLOW_IPS
from agent_registry.server import app
from common.cert.cert_validater import CertValidator
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import LogLevel, OperationResult, OperatorObject, OperationName
from common.util.cipher_util import DEFAULT_ENCODING
from common.util.conf_util import conf_singleton_obj, load_cert_password, set_ssl_folder_permissions
from common.util.config_util import get_conf

audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)


def get_user_info_from_env():
    """从环境变量获取用户信息"""
    user_info = {
        'username': os.environ.get('APP_USER', 'unknown'),
        'uid': os.environ.get('APP_UID', 'unknown'),
        'gid': os.environ.get('APP_GID', 'unknown'),
    }
    return user_info


async def record_startup_log():
    server_config = get_conf()
    await audit_handle.handle({
        "operation_name": OperationName.START_SERVICE,
        "level": LogLevel.DANGER,
        "result": OperationResult.SUCCESS,
        "object_name": OperatorObject.SERVICE,
        "details": {"ip": server_config.get("ip", ""), "port": server_config.get("port", "")},
        "user_name": get_user_info_from_env().get('username')
    })


app.add_event_handler("startup", record_startup_log)


def customized_create_ssl_context(
        certfile: str | os.PathLike[str],
        keyfile: str | os.PathLike[str] | None,
        password: str | None,
        ssl_version: int,
        cert_reqs: int,
        ca_certs: str | os.PathLike[str] | None,
        ciphers: str | None,
) -> ssl.SSLContext:
    try:
        ctx = ssl.SSLContext(ssl_version)
        get_password = (lambda: password) if password else None
        ctx.load_cert_chain(certfile, keyfile, get_password)
        ctx.verify_mode = ssl.VerifyMode(cert_reqs)
        if ca_certs:
            ctx.load_verify_locations(ca_certs)
            if len(conf_singleton_obj.get_crl_list()) > 0:
                # 如果有CRL的场景，追加CRL
                ctx.load_verify_locations(conf_singleton_obj.ssl_crl_file)
                # 配置为校验CRL模式
                ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
        if ciphers:
            ctx.set_ciphers(ciphers)
        return ctx
    except BaseException as e:
        logger.error(f"customized_create_ssl_context error {e}")
        raise e


# 由于原版config不支持加载crl，因此扩展crl支持
config.create_ssl_context = customized_create_ssl_context


class CustomUvicornServer:
    """Customized Uvicorn server, which is used to add additional security configurations."""

    def __init__(self, server_config, conf_obj):
        self.server_config = server_config
        self.conf_obj = conf_obj

    def run(self):
        os.environ.setdefault("FORWARDED_ALLOW_IPS", self.server_config.get(FORWARDED_ALLOW_IPS))
        server_config = uvicorn.Config(
            app=app,
            host=self.server_config.get("ip", "127.0.0.1"),
            port=int(self.server_config.get("port", 5000)),
            # ssl_certfile=self.conf_obj.ssl_certfile,
            # # 私钥路径
            # ssl_keyfile=self.conf_obj.ssl_keyfile,
            # # 私钥密码
            # ssl_keyfile_password=load_cert_password(self.conf_obj.ssl_keyfile_password).decode(DEFAULT_ENCODING),
            # # 信任证书
            # ssl_ca_certs=self.conf_obj.ssl_ca_certs,
            # # 是否校验客户端证书，填了如果浏览器没证书就没法访问了
            # ssl_cert_reqs=self.conf_obj.verify_client,
            # ssl_ciphers=CipherConverter.convert(self.server_config.get(TLS_CIPHER)),
            timeout_keep_alive=0,
            timeout_graceful_shutdown=int(self.server_config.get(CONN_TIMEOUT, 30)),
            log_level="info",
            proxy_headers=True
        )
        server = uvicorn.Server(server_config)
        server.run()


def main():
    server_config = get_conf()
    try:
        # 校验配置
        conf_obj = conf_singleton_obj
        # result = CertValidator(conf_obj).validate()
        # if not result.is_valid:
        #     sys.exit(result.message)
        # 通过校验后修改etc/ssl文件夹权限为700，里面文件权限为600
        set_ssl_folder_permissions()
        # 创建并启动服务器
        server = CustomUvicornServer(server_config, conf_obj)
        server.run()
    except Exception as e:
        logger.error(f"agent_registry server start failed {e}")
        asyncio.run(audit_handle.handle({
            "object_name": OperatorObject.SERVICE,
            "operation_name": OperationName.START_SERVICE,
            "level": LogLevel.DANGER,
            "result": OperationResult.FAILURE,
            "details": {"ip": server_config.get("ip", ""), "port": server_config.get("port", "")},
            "user_name": get_user_info_from_env().get('username')
        }))
        sys.exit(f"agent_registry server start failed: {e}")


if __name__ == "__main__":
    main()