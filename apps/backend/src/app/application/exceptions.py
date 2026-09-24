class ApplicationError(Exception):
    """应用层异常基类。"""


class EntityNotFoundError(ApplicationError):
    def __init__(self, entity: str, identifier: object) -> None:
        super().__init__(f"{entity}不存在: {identifier}")
        self.entity = entity
        self.identifier = identifier


class EntityAlreadyExistsError(ApplicationError):
    def __init__(self, entity: str, identifier: object) -> None:
        super().__init__(f"{entity}已存在: {identifier}")
        self.entity = entity
        self.identifier = identifier
