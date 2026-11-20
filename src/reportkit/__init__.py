"""reportkit: declarative periodic reports with a swappable brand kit.

Public API (see README):

* loading: :func:`load_period`, :func:`load_range` -> :class:`Period`
* metrics: :func:`summarize`, :func:`summarize_by`, :func:`failures_by`, :func:`with_total`,
  :func:`clean_rate_lower_bound`
* catalogue: :class:`ReportCatalog`, :func:`draw`
* comments: :class:`CommentStore`
* rendering: :class:`BrandDocument`, :func:`compose_pdf`, :func:`md_to_docx`, :func:`md_to_pptx`
* composition: :func:`build_report`
* validation: :func:`contrast`
"""

from .brand import BrandKit
from .catalog import ReportCatalog
from .charts import ChartSpec, Figure, draw
from .comments import Comment, CommentStore
from .loaders import load_period, load_range
from .metrics import (
    CLEAN_RATE,
    CONFORMITY_RATE,
    RateWithBase,
    Summary,
    clean_rate_lower_bound,
    failures_by,
    summarize,
    summarize_by,
    with_total,
)
from .model import Period, Result, Warning
from .placeholders import COMMENT_TOKEN, PENDING_TOKEN, SYNTHETIC_TAG
from .render_docx import BrandDocument, CoverData
from .render_md import md_to_docx, md_to_pptx, parse_markdown
from .render_pdf import PdfCover, compose_pdf
from .report import ReportRequest, ReportResult, build_report
from .schema import DataSchema, GroupCatalog, ItemCatalog
from .validator import ContrastReport, contrast

__version__ = "0.1.0"

__all__ = [
    "CLEAN_RATE",
    "COMMENT_TOKEN",
    "CONFORMITY_RATE",
    "PENDING_TOKEN",
    "SYNTHETIC_TAG",
    "BrandDocument",
    "BrandKit",
    "ChartSpec",
    "Comment",
    "CommentStore",
    "ContrastReport",
    "CoverData",
    "DataSchema",
    "Figure",
    "GroupCatalog",
    "ItemCatalog",
    "PdfCover",
    "Period",
    "RateWithBase",
    "ReportCatalog",
    "ReportRequest",
    "ReportResult",
    "Result",
    "Summary",
    "Warning",
    "__version__",
    "build_report",
    "clean_rate_lower_bound",
    "compose_pdf",
    "contrast",
    "draw",
    "failures_by",
    "load_period",
    "load_range",
    "md_to_docx",
    "md_to_pptx",
    "parse_markdown",
    "summarize",
    "summarize_by",
    "with_total",
]
