"""TCD08 report generation service package.

这个包放 TCD08 业务专属逻辑：
- report.py：报告生成主流程。
- rules.py：TCD08 JSON 规则解释和表单字段匹配。

通用能力仍然放在并列 service 中，例如：
- services.datamerge：占位符填充和 project_info 展平。
- services.word_sections：Word 文档删除、改写和 TOC 更新入口。
"""

from services.tcd08.report import generate_tcd08_report

__all__ = ["generate_tcd08_report"]
