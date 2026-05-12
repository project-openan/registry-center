# 自定义接口使用说明

## 系统概述
系统允许用户为不同操作定义自定义实现，同时为常见操作提供默认实现。

## 主要特性
1. **抽象基类**：为所有处理器定义统一接口
2. **默认实现**：为常见操作提供内置处理器
3. **自定义扩展**：支持用户注册自定义处理器

## 安装使用
该模块设计为Python项目的组成部分，直接包含在项目结构中即可使用。

## 使用方法
### 1.默认处理器

- `decrypt`: 处理解密操作
- `audit`: 处理审计日志
- `authenticate`: 处理认证
- `insert`: 处理Agent数据保存
- `query`: 处理Agent数据查询
- `update`: 处理Agent数据修改
- `get`: 处理Agent精准查询
- `retrieve`: 处理Agent检索
- `deregister`: 处理Agent注销

### 2.自定义处理器
创建并注册自定义处理器,在common/custom目录下新增__init__.py和my_custom_handle.py文件，
在my_custom_handle.py文件中添加如下代码：
```python
from common.custom.custom_handle import BaseHandler

class MyCustomHandle(BaseHandler):
    async def handle(self, *args, **kwargs):
        # 自定义实现
        return "自定义结果"
```
在__init__.py文件中增加如下代码
```python
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.custom.my_custom_handle import MyCustomHandle

# register第一个参数interface_type为接口类型，比如要覆写认证接口，那么就应该传入InterfaceType.AUTHENTICATE，如果要覆写解密参数，那么应该传入InterfaceType.DECRYPT
# 映射关系如下：
# InterfaceType.DECRYPT  --> 解密
# InterfaceType.AUDIT  --> 记录审计日志
# InterfaceType.AUTHENTICATE  --> 认证
# InterfaceType.INSERT  --> 保存
# InterfaceType.QUERY  --> 查询
# InterfaceType.UPDATE  --> 更新
# InterfaceType.GET  --> 唯一查询
# InterfaceType.RETRIEVE  --> 检索
# InterfaceType.DEREGISTER  --> 注销
HandlerRegistry.register(InterfaceType.AUTHENTICATE, MyCustomHandle)
```

### 3.使用处理器
使用处理器（默认或自定义）：
```python
from common.custom.custom_handle import HandlerRegistry, InterfaceType

# 获取处理器实例
handle = HandlerRegistry.get_handler(InterfaceType.QUERY)

# 使用处理器
result = await handle.handle(...)
```

API参考
BaseHandle
所有处理器必须继承的抽象基类

方法：
handle(*args, **kwargs):需要子类实现的抽象方法

HandlerRegistry
处理器注册表

方法：
registry(interface_type, handler_class):

interface_type:InterfaceType枚举值
handler_class： BaseHandler的子类
get_handler(interface_type): 返回注册的处理器实例或默认实现

默认处理器
DecryptHandler
处理解密操作。

AuditHandler
处理审计日志。

AuthenticateHandler
处理认证。

InsertHandler
处理Agent保存。

QueryHandler
处理Agent查询。

UpdateHandler
处理Agent修改。

GetHandler
处理Agent精准查询。

RetrieveHandler
处理Agent精准查询。

DeregisterHandler
处理Agent注销。