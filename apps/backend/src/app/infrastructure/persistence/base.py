from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类（Alembic 迁移以此为元数据来源）。"""
