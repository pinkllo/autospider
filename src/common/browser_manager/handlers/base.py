from abc import ABC, abstractmethod
from playwright.async_api import Page


class BaseAnomalyHandler(ABC):
    """
    异常处理抽象基类。
    所有特定的异常（如登录、验证码、风控）都必须继承此类。
    """

    # 默认优先级：数字越小越优先执行（登录检测通常设为 10，验证码 20，风控 30 等）
    priority: int = 100

    # 是否启用（可在子类中覆盖，但通常通过 registry 控制）
    enabled: bool = True

    @property
    @abstractmethod
    def name(self) -> str:
        """处理器名称，用于日志输出和注册表标识"""
        pass

    @abstractmethod
    async def detect(self, page: Page) -> bool:
        """
        探测逻辑：返回当前页面是否触发了该异常。
        注意：此方法应尽可能轻量，避免阻塞统一巡检流程。
        """
        pass

    @abstractmethod
    async def handle(self, page: Page) -> None:
        """
        处理逻辑：当 detect 返回 True 时触发。
        可以在此进行人工介入接管、自动打码或任务重试等操作。
        """
        pass
