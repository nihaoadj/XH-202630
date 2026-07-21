"""
测试辅助函数

提供测试过程中重置DI容器的工具函数，确保测试隔离。
"""
from app.containers import Container, init_container


def reset_container() -> Container:
    """重置依赖注入容器，创建全新实例

    在测试开始前调用，确保每个测试都使用全新的Container实例。

    示例：
        from app.utils.testing import reset_container

        def setup_function():
            container = reset_container()  # 创建全新容器

        def test_learner_service():
            container = reset_container()
            service = container.learner_service()  # 获取全新Service实例
    """
    return init_container()


def override_repository(container: Container, mock_repo):
    """使用override机制替换Repository实现

    在测试中使用Mock Repository替换真实实现，退出with块后自动恢复。

    示例：
        from app.utils.testing import reset_container, override_repository
        from unittest.mock import Mock

        def test_with_mock():
            container = reset_container()
            mock_repo = Mock()

            with override_repository(container, mock_repo):
                service = container.learner_service()
                # service会自动使用mock_repo

            # 退出with块后自动恢复真实实现

    Args:
        container: DI容器实例
        mock_repo: Mock Repository实例

    Returns:
        上下文管理器，退出时自动恢复
    """
    return container.learner_repository.override(mock_repo)