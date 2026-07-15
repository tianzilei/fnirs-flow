# Package Profile Specification

Updated: 2026-07-15

This document describes the default package profiles, import/export behavior,
and custom executable atom quarantine rules exposed in the public release.

## 1. 三类默认 Package Profile

### 1.1 design_review_package

**用途**：合作者或审稿人审核分析方案。

**默认内容**：

- ProjectSnapshot
- Flow（flow_snapshot.json、node_manifest.json、adapter_manifest.json）
- risk（risk_register.json、risk_rules.json）
- evidence（evidence_manifest.json）
- reports（analysis_plan.md、methods_rationale.md、validation_report.md、citation_report.md）

**不包含**：

- run ActionAttempt
- 原始数据
- 大型中间产物
- deidentification 层

**Reviewer Mode 入口**：直接进入只读 inspect 模式。

### 1.2 reproducibility_package

**用途**：relink data 后复现运行。

**默认内容**：

- ProjectSnapshot
- compiled manifests（plan.json、execution_dag.json、data_manifest.json、reproducibility_manifest.json）
- data（data_registry.json、relink_instructions.md）
- selected ActionAttempt（run/artifact_manifest.json、run/failure_manifest.json）
- reports（run_report.md）

**不包含**：

- 原始数据
- 历史 ActionAttempt
- deidentification 层（除非用户显式选择）

**Reviewer Mode 入口**：inspect -> relink data -> fork -> readiness check -> rerun。

### 1.3 submission_package

**用途**：投稿/补充材料。

**默认内容**：

- reports（analysis_plan.md、methods_rationale.md、validation_report.md、citation_report.md、run_report.md）
- citation（CITATION.md、CITATION.bib、CITATION.html、CITATION.tex）
- methods rationale
- validation report
- package manifest

**不包含**：

- 完整 Flow 定义
- 原始数据
- 大型中间产物
- custom executable atom 源码

**Reviewer Mode 入口**：只读查看报告和引用。

## 2. 导入/导出行为

### 2.1 导出规则

- Package 默认导出当前 ProjectSnapshot。
- 用户可选择附加 ActionAttempt（run、report、export、package）。
- 历史默认不打包；用户显式选择 `include_history` 时增加 `history/snapshots.jsonl`。
- custom executable atom 的代码、依赖、runtime manifest、dependency manifest、capability manifest、checksum 放入 `flow/custom_nodes/`。
- RiskRule 子集、readonly imported rules、trust RiskItems 和 accepted risk fields 进入 `risk/`。

### 2.2 导入规则

- Package 默认可导入查看。
- 如果只包含设计/计划层，可编辑并分支。
- 如果包含 run、reports、export 或 deidentification ActionAttempt，这些 attempt 不可变。
- 可 fork 成新的 Flow branch，并在新 branch 上 relink data 或 rerun。
- 导入的 project-scoped RiskRule 默认只读。若要修改或继续复用，必须复制成本地 project-scoped RiskRule。

## 3. Custom Executable Atom Quarantine 规则

### 3.1 导入时状态

导入 package 中的自建 executable atom 默认进入 `quarantined` 状态。

quarantined 行为：

- 只能查看 Flow、manifest、代码摘要、参数和风险。
- 不能自动执行。
- 如果 package 中缺少源码、manifest、checksum 或 dependency manifest，该 atom 为 `Blocked`。
- 如果源码存在但 checksum 与 manifest 不一致，该 atom 为 `Blocked`。

### 3.2 Trust 确认流程

用户确认 trust 后：

- 只在当前项目内、当前 checksum 下生效。
- 不跨项目、包、版本或 checksum 传播。
- 确认记录写入 `risk_register.json` 的 `risk_type: trust` RiskItem。
- 确认记录至少包含：affected custom atom、atom version、atom checksum、accepted_by、accepted_at、acceptance_note。

### 3.3 重新导出规则

重新导出时，必须保留：

- 原始 imported_package reference。
- 本地确认 RiskItem。
- checksum。
- capability manifest。
- 修改 diff。

## 4. Risk 提示差异

| Profile | 风险提示重点 |
|---|---|
| design_review_package | 方法学风险、参数选择风险、证据适用性 |
| reproducibility_package | 数据可用性、环境差异、依赖版本 |
| submission_package | 引用完整性、报告可追溯性、脱敏合规性 |

## 5. 导出向导差异

| Profile | 导出向导步骤 |
|---|---|
| design_review_package | 选择 snapshot -> 确认 risk 层 -> 选择 evidence level -> 导出 |
| reproducibility_package | 选择 snapshot -> 选择 ActionAttempt -> 确认 data manifest -> 确认 relink instructions -> 导出 |
| submission_package | 选择 snapshot -> 选择报告 -> 确认 citation -> 确认脱敏 -> 导出 |
