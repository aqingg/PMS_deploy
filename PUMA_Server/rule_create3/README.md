# Rule Create3：规则清单 xlsx → JSON

业务在 **规则清单** 中填写下拉项；开发在 **技术映射** 中维护模板 ID、`when_ref`、删除组号与替换原文。

## 生成 JSON

在仓库根目录执行：

```powershell
python PUMA_Server/rule_create3/generate_rules.py --from-catalog PUMA_Server/rule_create3/tcd08_rule_catalog_example_line39.xlsx
```

默认从 `config/tcd08_section_rules.json` 读取完整的 `condition_refs` 定义，输出中只保留本表引用的条目。

```powershell
python PUMA_Server/rule_create3/generate_rules.py --from-catalog ... --output PUMA_Server/config/tcd08_section_rules.json
python PUMA_Server/rule_create3/generate_rules.py --validate PUMA_Server/rule_create3/generated_catalog_rules.json
```

## 工作簿结构

| Sheet | 维护人 | 作用 |
| --- | --- | --- |
| `规则清单` | 业务 | 序号、规则类型、章节、段落、条件、结果 |
| `技术映射` | 开发 | 模板 ID ↔ 清单序号、`when_ref`、删除红段组、替换表 |
| `章节删除` | 业务/开发 | 生成 `calibration_scope.delete_when_missing`（按关键词触发整章删除） |
| `枚举` | 可选 | 下拉数据源（可隐藏） |

`章节删除` sheet 推荐列名：

- `启用`
- `检查字段`（默认建议填 `Calibration Scope`）
- `关键词(任一)`（支持 `|` 或逗号分隔）
- `删除章节`（支持 `|`、逗号或空格分隔，例如 `3.2|3.2.2`）
- `说明`

## 测试

```powershell
cd PUMA_Server
python -m unittest rule_create3.test_catalog
```
