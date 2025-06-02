from typing import Any
from sqlalchemy import Column, Integer # Added for the optional ID column
from sqlalchemy.ext.declarative import as_declarative, declared_attr

@as_declarative()
class Base:
    """
    Base class for all SQLAlchemy models.
    It includes an automatic __tablename__ generator and an optional
    default integer primary key column named 'id'.
    """
    # Optional: Define a default primary key for all models inheriting from Base.
    # If you prefer to define primary keys on a per-model basis,
    # you can remove this 'id' attribute from the Base class.
    # The `initial_migration.py` suggests integer PKs are used.
    id: Any = Column(Integer, primary_key=True, index=True) # Making it a real column definition

    __name__: str # Standard attribute, used by __tablename__

    # Generate __tablename__ automatically
    @declared_attr
    def __tablename__(cls) -> str:
        """
        Generates a lowercase table name from the model's class name.
        e.g., class User -> table name 'user'
        """
        return cls.__name__.lower()