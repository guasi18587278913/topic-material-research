# 素材包与验收

## 两层交付

简短概览帮助用户做选择，同时保留可继续创作的详细材料。推荐任务目录：

```
research/日期-主题/
  overview.md       可讲角度、推荐、重要证据与缺口
  materials.md      详细材料卡，按问题/人物/过程组织，不只按平台堆链接
  bundle.json       来源、材料、角度与方法的可核对关联
  raw/              脱敏后的完整原始返回、网页或逐字稿
  receipts/         调用回执与核价记录
  budget.json       本任务授权范围和上限
  ledger.jsonl      逐次调用、成功/失败、费用依据
```

只要计划或少量整理时按范围缩减，不凑空目录。原始数据和详细材料优先于额外展示页面。

## 材料卡

每条有稳定编号，记清：

- 回答哪个问题，可用于哪个角度/方法；
- 具体发生了什么：人物、动作、时间、场景、过程、数字与条件；
- 关键原话及前后语境；自己的概括与译文另标，不冒充引语；
- 原始 URL、发布者/说话者、发表/事件/采集时间，段落或音视频时间点；
- 原文、转述、自述、推断、待核、被反证分别标注；
- 能支持到哪里，不能推出什么，有什么相反材料；
- 可展示的证据与画面线索；截图和示意图区分，许可未知不声称可任意商用。

不要把长报道压成一句结论后丢掉中间过程。同一来源可拆多张卡，仍保留同一原始来源身份。来源本身“说了 X”可核，不等于 X 的效果已独立验证。

## bundle.json 最小合同

合同用于链接和原文一致性检查，不给内容质量打虚假分数。

```json
{
  "schema_version": 1,
  "topic": "用户原题，锁定范围写在 overview 中",
  "sources": [{
    "id": "S1", "url": "https://example.com/original", "origin_group": "original-interview-1",
    "access": "full_text", "raw_path": "raw/source-1.json", "sha256": "实际摘要"
  }],
  "materials": [{
    "id": "M1", "source_id": "S1", "locator": "第 4 段或 00:03:20",
    "excerpt": "原件中实际存在的原话", "detail": "保留过程与细节的提取",
    "status": "attributed", "supports": "支持到哪", "limits": "尚不能证明什么"
  }],
  "angles": [{
    "id": "A1", "question": "值得研究的具体问题", "readiness": "explore",
    "basis_material_ids": ["M1"], "method_slugs": ["concepts/body_expression#16"],
    "missing": ["关键证据缺口"], "distinct_by": "真正改变了什么"
  }],
  "methods": [{"slug": "concepts/body_expression#16", "decision": "used", "action": "实际改变的采集动作", "material_ids": ["M1"]}],
  "gaps": [{"question": "仍缺什么", "priority": "core", "next_action": "具体去哪查什么"}]
}
```

- `access`：`full_text` / `transcript` / `direct_record` / `search_snippet` / `metadata`。
- `status`：`verified`（本轮核对的事实）、`attributed`（保留归属的来源自述/观点）、`unverified`、`inference`、`contradicted`。旧包“已核”是旧记录，关键引用回看原件，不能自动升级本轮核验。
- `readiness`：`explore`（研究方向成立）、`draftable`（中心承诺已有材料支撑）、`blocked`（关键材料缺失）。提议实验是 explore，不把计划改成已取得结果。
- `draftable` 的中心依据须可回查；搜索摘要不能单独支撑它；未核/推断/被反证的材料不能伪装成事实基础。可以把这些材料保留在包里讨论。
- 判断对象也要分开：默认 `claim_scope: event` 表示事件/效果主张。仅核对原件字段、页面表述或文字算式时，可明确写 `claim_scope: source_record`，并在 supports/limits 说清观察对象。已核的账号名、发布时间等字段可由完整保存的 metadata 作证，无需假称读过内容全文；这个标记不能用来证明企业经历或给未核事件升级。检查器只核这个声明与访问类型是否兼容，仍需人工核对主张本身。
- 原文受限时可保留无引语的卡，`excerpt` 留空并解释访问限制；不能伪造引语通过校验。
- 全文可读但只需转述时也可留空 excerpt，并说明不摘引的理由；不为了消除提示而添加引语。OCR 的原始识别结果保留不动，另记对应图片、看图核对页码、仍为机器识别的页码与勘误。同源关系尚未确认时明确标为待追溯的保守分组，不能把分组当已查清传播链。

```bash
python3 scripts/bundle.py init /absolute/TASK --topic '用户原题'
python3 scripts/bundle.py check /absolute/TASK
```

用 `bundle.py add-source` 将 collector 的完整 raw 登记到同一包中；它计算 SHA-256，不代替内容核验。人工提取后再补材料、角度与方法。

## 两类验收

**可追溯与边界**：来源可打开或有保存原件；引用与数字对得上；原始来源去重；因果与相关分开；自述归属清楚；国内外、版本、时间与统计口径不混用；失败查询未记成零结果。

**创作可用性**：选中方法所需材料齐不齐；是否留下具体人物、动作、场景、过程或选择；论据是否有不同维度及成立条件；观众问题是否真实或明确为假设；有无相对原资讯的增量。无需每题全部具备。

概览对主要角度说明能用、待补还是不适合，并给依据。方法记录能指出改变了什么，只报术语不通过。锁定角度不擅改，但可以明确“尚不足以兑现这个表述”；前提被材料否定时，按 SKILL.md 给出现有材料撑得住的说法。

## 停止条件

中心问题与读者价值明确；重要判断可回查；选中方法的关键材料齐备；反证和条件已处理；新资料主要重复时进入整理。

因预算、权限、平台错误或缺采访机会停止，标为部分完成，给最高优先级缺口和下一步。资料条数、平台数量、检查通过与真实传播效果分别报告。
