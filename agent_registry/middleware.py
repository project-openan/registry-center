# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# middleware.py
import asyncio
from fastapi import Request, status
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware



class ConnectionLimitMiddleware(BaseHTTPMiddleware):
    """Connection limit middleware"""

    def __init__(self, app, max_connections: int):
        super().__init__(app)
        self.max_connections = max_connections
        self.active_connections = 0
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        async with self._lock:
            if self.active_connections >= self.max_connections:
                logger.error(f"The server is at maximum connection capacity. ({self.max_connections})")
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "code": status.HTTP_503_SERVICE_UNAVAILABLE,
                        "message": f"The server is at maximum connection capacity. ({self.max_connections})"
                    }
                )
            self.active_connections += 1

        try:
            response = await call_next(request)
            return response
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "message": "Internal Server Error"
                }
            )
        finally:
            async with self._lock:
                self.active_connections -= 1


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Timeout control middleware"""

    def __init__(self, app, timeout_seconds: int):
        super().__init__(app)
        self.timeout_seconds = timeout_seconds

    async def dispatch(self, request: Request, call_next):
        try:
            # Apply timeout
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout_seconds
            )
            return response
        except asyncio.TimeoutError:
            logger.error(f"Request processing timeout. ({self.timeout_seconds}s)")
            return JSONResponse(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                content={
                    "code": status.HTTP_504_GATEWAY_TIMEOUT,
                    "message": f"Request processing timeout. ({self.timeout_seconds}s)"
                }
            )
