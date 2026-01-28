"""Redis 队列管理模块 - 支持 ACK 机制和故障转移的可靠消息队列

基于 Redis Stream + Hash 架构：
- Hash: 存储全量数据，支持去重
- Stream: 任务队列，支持 ACK、Consumer Group、故障转移

存储结构：
1. Data Hash:
   - Key: {key_prefix}:data
   - Field: {item_hash}
   - Value: JSON {"url": "...", "created_at": "...", "metadata": {...}}

2. Task Stream:
   - Key: {key_prefix}:stream
   - Entry: {"data_id": "{item_hash}"}

3. Consumer Group:
   - Group Name: {key_prefix}:workers
   - Consumer Name: 由调用方指定（通常是进程ID或机器名）
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any
import logging
import hashlib
import json
import time

import redis.asyncio as aioredis

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisQueueManager:
    """Redis 可靠队列管理器

    功能特性：
    - 基于 Stream 的消息队列
    - ACK 确认机制
    - 故障转移（自动 Claim 超时任务）
    - 自动去重（基于 Hash）
    - Consumer Group 多消费者并发

    Args:
        host: Redis 服务器地址
        port: Redis 端口
        password: Redis 密码
        db: Redis 数据库索引
        key_prefix: 存储键的前缀（如 "autospider:urls"）
        logger: 可选的日志记录器
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str | None = None,
        db: int = 0,
        key_prefix: str = "autospider:urls",
        logger: logging.Logger | None = None,
    ):
        self.host = host
        self.port = port
        self.password = password
        self.db = db
        self.key_prefix = key_prefix
        self.client: Redis | None = None
        self.logger = logger or logging.getLogger(__name__)

        # Key 名称
        self.data_key = f"{key_prefix}:data"
        self.stream_key = f"{key_prefix}:stream"
        self.group_name = f"{key_prefix}:workers"

    def _generate_hash_id(self, item: str) -> str:
        """生成 item 的稳定 hash ID

        使用 SHA256 的前 16 位作为 ID，确保：
        1. 相同 item 总是生成相同 ID
        2. ID 足够短，节省内存
        3. 碰撞概率极低

        Args:
            item: 数据项（如 URL）

        Returns:
            16 位十六进制 hash ID
        """
        return hashlib.sha256(item.encode("utf-8")).hexdigest()[:16]

    def _format_connection_summary(self, timeout_seconds: int) -> str:
        password_status = "set" if self.password else "empty"
        return (
            f"host={self.host}, port={self.port}, db={self.db}, "
            f"key_prefix={self.key_prefix}, timeout={timeout_seconds}s, "
            f"password={password_status}"
        )

    async def connect(self) -> Redis | None:
        """连接到 Redis 服务器

        Returns:
            Redis 客户端实例，连接失败返回 None
        """
        try:
            connect_timeout = 2
            self.client = aioredis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                db=self.db,
                decode_responses=True,
                socket_connect_timeout=connect_timeout,
            )

            # 测试连接
            await self.client.ping()
            self.logger.info(
                f"已连接到 Redis {self.host}:{self.port}，数据库: {self.db}，Key 前缀: {self.key_prefix}"
            )

            # 初始化 Consumer Group（如果不存在）
            await self._ensure_consumer_group()

            return self.client

        except (ConnectionRefusedError, TimeoutError, aioredis.ConnectionError) as e:
            self.logger.error(f"Redis 连接失败: {e}")
            self.logger.error(f"Redis 连接参数: {self._format_connection_summary(connect_timeout)}")
            self.logger.info("请确保 Redis 服务正在运行")

            # 连接失败，关闭客户端
            if self.client:
                await self.client.close()
                self.client = None

        except Exception as e:
            self.logger.error(f"Redis 连接时发生未知错误: {e}")
            self.logger.error(f"Redis 连接参数: {self._format_connection_summary(connect_timeout)}")
            if self.client:
                await self.client.close()
                self.client = None

        return None

    async def _ensure_consumer_group(self) -> None:
        """确保 Redis Stream 的消费者组 (Consumer Group) 存在。
        
        如果 Stream 不存在，会使用 mkstream=True 自动创建。
        如果 Group 已存在，会忽略 BUSYGROUP 错误。
        """
        if not self.client:
            return

        try:
            # 尝试创建 Consumer Group，从头 ("0") 开始读取
            await self.client.xgroup_create(
                self.stream_key, self.group_name, id="0", mkstream=True
            )
            self.logger.info(f"已创建 Consumer Group: {self.group_name}")
        except aioredis.ResponseError as e:
            # BUSYGROUP 错误表示 Group 已存在，是正常情况
            if "BUSYGROUP" in str(e):
                self.logger.debug(f"Consumer Group 已存在: {self.group_name}")
            else:
                self.logger.error(f"创建 Consumer Group 失败: {e}")
                raise

    # ==================== 队列操作 API ====================

    async def push_task(self, item: str, metadata: dict[str, Any] | None = None) -> bool:
        """将数据推入队列

        1. 存入 Hash（去重）
        2. 发布到 Stream（任务队列）

        Args:
            item: 数据项（如 URL）
            metadata: 可选的元数据

        Returns:
            是否成功推入（False 表示数据已存在，已去重）
        """
        if not self.client:
            return False

        try:
            hash_id = self._generate_hash_id(item)

            # 构建存储数据
            data = {
                "url": item,
                "created_at": int(time.time()),
            }
            if metadata:
                data["metadata"] = metadata

            data_json = json.dumps(data, ensure_ascii=False)

            # 1. 存入 Hash（HSETNX 去重）
            is_new = await self.client.hsetnx(self.data_key, hash_id, data_json)

            if not is_new:
                self.logger.debug(f"数据项已存在（去重）: {item[:60]}...")
                return False

            # 2. 发布任务到 Stream
            await self.client.xadd(self.stream_key, {"data_id": hash_id})

            self.logger.debug(f"已推入任务: {item[:60]}...")
            return True

        except Exception as e:
            self.logger.error(f"推入任务失败: {e}")
            return False

    async def push_tasks_batch(
        self, items: list[str], metadata_list: list[dict[str, Any]] | None = None
    ) -> int:
        """批量推入任务，利用 Redis Pipeline 提高吞吐量。

        Args:
            items: 数据项（如 URL）列表。
            metadata_list: 与 items 对应的元数据列表。

        Returns:
            成功推入的新任务数量（排除已存在的重复项）。
        """
        if not self.client or not items:
            return 0

        success_count = 0

        try:
            # 使用 pipeline 减少网络往返开销
            async with self.client.pipeline() as pipe:
                for i, item in enumerate(items):
                    hash_id = self._generate_hash_id(item)

                    data = {
                        "url": item,
                        "created_at": int(time.time()),
                    }
                    if metadata_list and i < len(metadata_list):
                        data["metadata"] = metadata_list[i]

                    data_json = json.dumps(data, ensure_ascii=False)

                    # 检查是否存在并存入 Hash
                    pipe.hsetnx(self.data_key, hash_id, data_json)
                    # 发布到 Stream
                    pipe.xadd(self.stream_key, {"data_id": hash_id})

                results = await pipe.execute()

            # results 中每两个元素对应一个项的操作结果 [HSETNX_result, XADD_result]
            for i in range(0, len(results), 2):
                if results[i]:  # HSETNX 返回 1 表示是新插入的数据
                    success_count += 1

            self.logger.info(f"批量推入完成: {success_count}/{len(items)} 个新任务")
            return success_count

        except Exception as e:
            self.logger.error(f"批量推入任务异常: {e}")
            return success_count

    async def fetch_task(
        self, consumer_name: str, block_ms: int = 5000, count: int = 1
    ) -> list[tuple[str, str, dict]]:
        """从消费者组中获取任务。获取到的消息会进入该消费者的 PEL。

        Args:
            consumer_name: 当前消费者的唯一名称。
            block_ms: 如果队列为空，阻塞等待的毫秒数。0 表示立即返回。
            count: 单词获取的任务上限。

        Returns:
            任务列表 [(StreamID, HashID, DataDict), ...]。
        """
        if not self.client:
            return []

        try:
            # ">" 表示获取从未分配给任何消费者的新消息
            response = await self.client.xreadgroup(
                groupname=self.group_name,
                consumername=consumer_name,
                streams={self.stream_key: ">"},
                count=count,
                block=block_ms,
            )

            if not response:
                return []

            tasks = []
            for _, messages in response:  # response: [[stream_key, [msg, ...]]]
                for stream_id, fields in messages:
                    data_id = fields.get("data_id")
                    if not data_id:
                        continue

                    # 根据索引 HashID 获取实际数据内容
                    data_json = await self.client.hget(self.data_key, data_id)
                    if data_json:
                        data = json.loads(data_json)
                        tasks.append((stream_id, data_id, data))

            if tasks:
                self.logger.debug(f"消费者 [{consumer_name}] 成功获取 {len(tasks)} 个任务")
            return tasks

        except Exception as e:
            self.logger.error(f"消费任务异常: {e}")
            return []

    async def ack_task(self, stream_id: str) -> bool:
        """确认任务已完成

        Args:
            stream_id: 任务的 Stream ID

        Returns:
            是否成功确认
        """
        if not self.client:
            return False

        try:
            # 从 PEL 中移除消息
            result = await self.client.xack(self.stream_key, self.group_name, stream_id)

            if result:
                self.logger.debug(f"已 ACK 任务: {stream_id}")

            return bool(result)

        except Exception as e:
            self.logger.error(f"ACK 任务失败: {e}")
            return False

    async def fail_task(
        self, stream_id: str, data_id: str, error_msg: str | None = None, max_retries: int = 3
    ) -> bool:
        """标记任务失败并实现重试机制

        工作流程：
        1. 读取当前重试次数
        2. 如果未超过最大重试次数：
           - 增加重试计数
           - **不 ACK**，让任务留在 PEL 中
           - 其他消费者可以通过 recover_stale_tasks() 捞回重试
        3. 如果超过最大重试次数：
           - ACK 任务（从 PEL 移除）
           - 移入死信队列（可选）
           - 记录失败信息

        Args:
            stream_id: 任务的 Stream ID
            data_id: 数据 Hash ID
            error_msg: 错误信息
            max_retries: 最大重试次数（默认 3 次）

        Returns:
            是否成功处理
        """
        if not self.client:
            return False

        try:
            # 1. 读取当前数据和重试次数
            data_json = await self.client.hget(self.data_key, data_id)
            if not data_json:
                self.logger.error(f"数据不存在: {data_id}")
                return False

            data = json.loads(data_json)
            metadata = data.get("metadata", {})

            # 从 metadata 中获取重试次数
            if isinstance(metadata, dict):
                retry_count = metadata.get("retry_count", 0)
            else:
                retry_count = 0

            # 2. 判断是否超过最大重试次数
            if retry_count < max_retries:
                # 未超过：增加重试计数，不 ACK，让任务留在 PEL 中
                new_retry_count = retry_count + 1

                if not isinstance(metadata, dict):
                    metadata = {}

                metadata["retry_count"] = new_retry_count
                metadata["last_error"] = error_msg
                metadata["last_failed_at"] = int(time.time())

                data["metadata"] = metadata

                await self.client.hset(self.data_key, data_id, json.dumps(data, ensure_ascii=False))

                self.logger.warning(
                    f"任务失败，将重试 ({new_retry_count}/{max_retries}): "
                    f"{data.get('url', 'Unknown')[:60]}, 错误: {error_msg}"
                )

                # 关键：不调用 XACK，让任务留在 PEL 中
                # 其他消费者可以通过 recover_stale_tasks() 捞回
                return True
            else:
                # 超过最大重试次数：彻底失败，ACK 并移入死信队列
                self.logger.error(
                    f"任务彻底失败（已重试 {retry_count} 次）: "
                    f"{data.get('url', 'Unknown')[:60]}, 最后错误: {error_msg}"
                )

                # ACK 任务（从 PEL 中移除）
                await self.client.xack(self.stream_key, self.group_name, stream_id)

                # 记录彻底失败的信息
                data["final_failed_at"] = int(time.time())
                data["final_error"] = error_msg
                data["total_retries"] = retry_count

                await self.client.hset(self.data_key, data_id, json.dumps(data, ensure_ascii=False))

                # 可选：移入死信队列
                dead_letter_key = f"{self.key_prefix}:dead_letter"
                await self.client.xadd(
                    dead_letter_key,
                    {
                        "data_id": data_id,
                        "url": data.get("url", ""),
                        "error": error_msg or "",
                        "retries": str(retry_count),
                        "failed_at": str(int(time.time())),
                    },
                )

                self.logger.info(f"任务已移入死信队列: {dead_letter_key}")
                return True

        except Exception as e:
            self.logger.error(f"标记失败任务时出错: {e}")
            return False

    async def recover_stale_tasks(
        self, consumer_name: str, max_idle_ms: int = 300000, count: int = 10
    ) -> list[tuple[str, str, dict]]:
        """捞回超时未 ACK 的任务（故障转移机制）。
        
        该方法使用 XAUTOCLAIM 查找那些已经在其他消费者 PEL 中停滞过久的任务，并将它们转移给当前消费者。

        Args:
            consumer_name: 接管任务的消费者名称。
            max_idle_ms: 最大空闲毫秒数。超过此时间未 ACK 的任务将被判定为停滞。
            count: 单词捞回的任务数上限。

        Returns:
            捞回的任务列表 [(StreamID, HashID, DataDict), ...]。
        """
        if not self.client:
            return []

        try:
            # 自动认领超时消息
            result = await self.client.xautoclaim(
                name=self.stream_key,
                groupname=self.group_name,
                consumername=consumer_name,
                min_idle_time=max_idle_ms,
                start_id="0-0",
                count=count,
            )

            # result: (next_start_id, [msg, ...], [deleted_ids])
            if not result or len(result) < 2:
                return []

            claimed_messages = result[1]
            if not claimed_messages:
                return []

            tasks = []
            for stream_id, fields in claimed_messages:
                data_id = fields.get("data_id")
                if not data_id:
                    continue

                data_json = await self.client.hget(self.data_key, data_id)
                if data_json:
                    data = json.loads(data_json)
                    tasks.append((stream_id, data_id, data))

            if tasks:
                self.logger.warning(
                    f"消费者 [{consumer_name}] 捞回 {len(tasks)} 个停滞任务 (空闲 > {max_idle_ms/1000}s)"
                )

            return tasks

        except Exception as e:
            self.logger.error(f"捞回停滞任务异常: {e}")
            return []

    # ==================== 查询 API ====================

    async def get_all_items(self) -> dict[str, dict]:
        """获取所有数据项

        Returns:
            字典 {hash_id: data_dict}
        """
        if not self.client:
            return {}

        try:
            items = await self.client.hgetall(self.data_key)

            result = {}
            for hash_id, data_json in items.items():
                result[hash_id] = json.loads(data_json)

            return result

        except Exception as e:
            self.logger.error(f"获取所有数据项失败: {e}")
            return {}

    async def get_item(self, item: str) -> dict | None:
        """获取单个数据项

        Args:
            item: 数据项（如 URL）

        Returns:
            数据字典，不存在则返回 None
        """
        if not self.client:
            return None

        try:
            hash_id = self._generate_hash_id(item)
            data_json = await self.client.hget(self.data_key, hash_id)

            if data_json:
                return json.loads(data_json)

            return None

        except Exception as e:
            self.logger.error(f"获取数据项失败: {e}")
            return None

    async def get_pending_count(self, consumer_name: str | None = None) -> int:
        """获取待处理任务数量

        Args:
            consumer_name: 消费者名称（可选，如果提供则仅统计该消费者的 PEL）

        Returns:
            待处理任务数量
        """
        if not self.client:
            return 0

        try:
            if consumer_name:
                # 获取特定消费者的 PEL 长度
                pending_info = await self.client.xpending(self.stream_key, self.group_name)
                # pending_info 格式: [total_pending, min_id, max_id, [[consumer, count]]]
                if pending_info and len(pending_info) > 0:
                    return pending_info[0]
            else:
                # 获取 Stream 长度
                length = await self.client.xlen(self.stream_key)
                return length

            return 0

        except Exception as e:
            self.logger.error(f"获取待处理任务数失败: {e}")
            return 0

    async def get_stats(self) -> dict[str, Any]:
        """获取队列统计信息

        Returns:
            统计信息字典
        """
        if not self.client:
            return {}

        try:
            stats = {
                "total_items": await self.client.hlen(self.data_key),
                "stream_length": await self.client.xlen(self.stream_key),
                "pending_count": 0,
                "consumers": [],
            }

            # 获取 PEL 信息
            try:
                pending_info = await self.client.xpending(self.stream_key, self.group_name)
                if pending_info and len(pending_info) > 0:
                    stats["pending_count"] = pending_info[0]
                    if len(pending_info) > 3:
                        stats["consumers"] = [
                            {"name": consumer, "pending": count}
                            for consumer, count in pending_info[3]
                        ]
            except Exception:
                pass

            return stats

        except Exception as e:
            self.logger.error(f"获取统计信息失败: {e}")
            return {}
