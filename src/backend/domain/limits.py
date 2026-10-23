"""Validated process budgets; configuration is injected at application composition."""

from pydantic import BaseModel, ConfigDict, Field

LIMITS = {"stl": 256, "pdf": 25, "docx": 25, "txt": 25, "md": 25, "png": 20, "jpg": 20, "jpeg": 20}


class InputLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    stl_mib: int = Field(default=256, ge=1, le=256)
    document_mib: int = Field(default=25, ge=1, le=25)
    image_mib: int = Field(default=20, ge=1, le=20)
    triangles: int = Field(default=2_000_000, ge=1, le=2_000_000)
    analysis_seconds: float = Field(default=120, gt=0, le=120)
    pdf_pages: int = Field(default=50, ge=1, le=50)
    page_seconds: float = Field(default=30, gt=0, le=30)
    image_pixels: int = Field(default=25_000_000, ge=1, le=25_000_000)
    expanded_docx_mib: int = Field(default=100, ge=1, le=100)
    companions: int = Field(default=20, ge=1, le=20)

    def file_mib(self, kind: str) -> int:
        if kind == "stl":
            return self.stl_mib
        if kind in {"png", "jpg", "jpeg"}:
            return self.image_mib
        return self.document_mib
