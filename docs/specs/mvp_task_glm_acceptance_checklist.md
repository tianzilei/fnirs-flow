# MVP Task GLM Flow 用户路径验收清单

生成日期：2026-07-10
最后更新：2026-07-15

## 1. 验收清单

### 1.1 新建项目

- [x] 用户可以创建新项目。
- [x] 用户可以选择 `Task GLM` 模板。
- [x] 系统生成初始粗粒度 Flow。
- [x] Flow 显示以下模块节点：Dataset、Study Design、QC、Preprocessing、Analysis、Reporting、Export。
- [x] 每个模块节点可展开为 Subflow。 (点击节点显示详情面板)

### 1.2 选择 Task GLM Template

- [x] Template 自动带入以下 MethodAtom：Dataset、Study Design、QC、Preprocessing、Design Matrix、First-level GLM、Contrast、Channel Output、ROI Output、Report/Export。
- [x] Template 自动带入以下 evidence references。
- [x] Template 自动带入以下 preset references：QC preset、preprocessing preset、GLM preset。 (default_config 包含 preset 值)

### 1.3 链接 demo dataset

- [x] 用户可以链接或导入 MNE-NIRS finger tapping dataset。
- [x] 系统检查 dataset 格式（BIDS/SNIRF）。
- [x] 系统检查 adapter 兼容性。
- [x] Dataset 节点状态变为 `configured`。

### 1.4 确认 conditions/control/contrasts

- [x] 系统显示从 study_design 提取的 conditions 列表。
- [x] 用户可以确认或修改 task conditions。
- [x] 用户可以确认或修改 control condition。
- [x] 用户可以确认或修改 contrasts。
- [x] Design Matrix 节点状态变为 `configured`。

### 1.5 确认 QC、motion、filter、ROI 和 export profile

- [x] 系统显示 QC preset 参数，用户可以确认或修改。
- [x] 系统显示 motion correction preset 参数，用户可以确认或修改。
- [x] 系统显示 filter preset 参数，用户可以确认或修改。
- [x] 系统显示 ROI strategy 参数，用户可以确认或修改。
- [x] 用户可以选择 export profile（submission / reviewer / reproducibility）。
- [x] 所有确认完成后，Readiness Check 状态为 `Ready`。

### 1.6 保存 ProjectSnapshot

- [x] 用户可以保存 ProjectSnapshot。
- [x] ProjectSnapshot 包含：flow、compiled、data、risk 层。
- [x] ProjectSnapshot 不可变。
- [x] 系统记录 snapshot_id、created_at、version_state、version_refs。

### 1.7 dry-run

- [x] 用户可以执行 dry-run。
- [x] dry-run 验证：schema validation、graph validation、adapter validation、readiness check。
- [x] dry-run 输出 risk register，列出所有 warning 和 error。
- [x] dry-run 不执行实际计算。

### 1.8 execute

- [x] 用户可以执行分析。
- [x] 系统先创建 ProjectSnapshot（如果有 draft changes）。 (execute 前自动创建)
- [x] 系统创建 ActionAttempt，引用 ProjectSnapshot。
- [x] 执行引擎按 execution 顺序执行 (preprocessing → analysis → output)。
- [x] 每个 MethodAtom 的执行状态记录在 ActionAttempt 中。
- [x] 执行完成后，ActionAttempt 状态为 `completed` 或 `failed`。
- [x] 执行过程中产生的 artifact 进入 artifact manifest。

### 1.9 查看 artifacts 和 reports

- [x] 用户可以查看以下 artifacts：design matrix、GLM results、ROI results。
- [x] 用户可以查看以下 reports：run_report.md、project_report。
- [x] 每个 reportlet 可追溯到 source MethodAtom、source artifact、parameters hash。
- [x] 用户可以查看 risk register。

### 1.10 导出 package

- [x] 用户可以选择导出 profile。
- [x] 系统按 profile 生成 Flow Package (.fnirsflow.zip)。
- [x] Package 包含：plan.json、execution_dag.json、data_manifest.json 等。
- [x] Package 不包含原始数据。

### 1.11 在新目录导入、relink、rerun

- [x] 用户可以在新目录导入 package。
- [x] 导入后，Flow 标记为只读。 (import_metadata.json + WebUI banner)
- [x] custom executable atom 进入 `quarantined` 状态。 (检查 registry，未知 atom 标记 quarantine)
- [x] 用户可以 relink data root。
- [x] 用户可以 fork 到新 branch。 (fork_package 创建可编辑副本)
- [x] 用户可以重新执行 trust 确认。 (Trust 按钮解除 quarantine)
- [x] 用户可以重新执行 readiness check。
- [x] 用户可以 rerun 分析。 (Fork 后移除 read_only，可正常 execute)

## 2. 验收标准

### 2.1 功能验收

- 46/46 checklist 项通过。 ✅
- 无 fatal error。 ✅
- 所有 high risk 已被用户确认。 ✅

### 2.2 可复现验收

- Package 可导出并导入。 ✅
- 所有参数、evidence 引用、risk 记录在 plan.json 中。 ✅
- 所有执行记录在 action_attempts.json 中。 ✅
