from enum import Enum
from typing import Optional

from pydantic import BaseModel


class PatchOperation(str, Enum):
    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"


class FilePatch(BaseModel):
    file_path: str
    operation: PatchOperation
    original_code: Optional[str] = None  # None for INSERT operations
    new_code: str
    start_line: int
    end_line: int
    description: str


class PatchSet(BaseModel):
    patches: list[FilePatch]
    total_files: int
    description: str
    applied: bool = False
    applied_at: Optional[str] = None
    branch_name: Optional[str] = None
