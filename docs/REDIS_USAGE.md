# Redis 模块使用说明

## 功能特性

新的 `RedisManager` 模块提供以下功能：

1. **自动连接管理**：智能连接 Redis，带连接超时和错误处理
2. **自动启动服务**：当检测到 Redis 未运行时，自动尝试启动 Redis 服务
3. **跨平台支持**：支持 Windows、Linux、macOS 多种启动方式
4. **断点续爬**：自动加载历史 URL，避免重复采集
5. **批量操作**：支持单个和批量保存 URL

---

## 启用 Redis

在 `.env` 文件中设置：

```bash
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_KEY_PREFIX=autospider:urls
```

---

## 自动启动 Redis

当你启用 Redis 但服务未运行时，`RedisManager` 会自动尝试启动：

### Windows 系统
会依次尝试以下命令：
1. `net start Redis` - Windows 服务
2. `wsl sudo service redis-server start` - WSL 中的 Redis
3. `redis-server --daemonize yes` - 直接运行

### Linux/macOS 系统
会依次尝试以下命令：
1. `sudo systemctl start redis`
2. `sudo systemctl start redis-server`
3. `sudo service redis-server start`
4. `redis-server --daemonize yes`

---

## 手动使用 RedisManager

```python
from autospider.redis_manager import RedisManager

# 创建管理器
redis_mgr = RedisManager(
    host="localhost",
    port=6379,
    key_prefix="my:urls",
    auto_start=True,  # 自动启动 Redis
)

# 连接（如果失败会自动尝试启动 Redis）
await redis_mgr.connect()

# 保存单个 URL
await redis_mgr.save_url("https://example.com")

# 批量保存
await redis_mgr.save_urls_batch([
    "https://example.com/1",
    "https://example.com/2",
])

# 加载已保存的 URL
urls = await redis_mgr.load_urls()

# 获取 URL 数量
count = await redis_mgr.get_count()

# 关闭连接
await redis_mgr.close()
```

---

## 验证 Redis 数据

```bash
# 查看所有 URL
redis-cli SMEMBERS autospider:urls

# 查看 URL 数量
redis-cli SCARD autospider:urls

# 清空所有 URL（谨慎使用）
redis-cli DEL autospider:urls
```

---

## 注意事项

1. **权限问题**：自动启动 Redis 可能需要管理员/sudo 权限
2. **安装检查**：确保已安装 Redis 服务
3. **端口冲突**：如果 6379 端口被占用，请修改 `REDIS_PORT`
4. **网络防火墙**：确保防火墙允许 Redis 端口访问
