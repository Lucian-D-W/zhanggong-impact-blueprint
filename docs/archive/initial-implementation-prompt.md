你现在是我的仓库内开发代理。请在当前仓库里实现一个 **Code Impact Guardian**，目标是让任何代码修改都先经过影响分析，再允许真正改代码。

# 目标

请实现以下能力：

1. 在仓库内增加一个 repo-scoped skill：
   - 路径：`.agents/skills/code-impact-guardian/`
   - 读取其中的 `SKILL.md`
   - 工作流要求：**先生成 impact report，再改代码**

2. 在仓库根目录增加或更新 `AGENTS.md`：
   - 规定任何代码改动任务都必须先使用 code-impact-guardian
   - 没有 `.ai/codegraph/reports/impact-<task-id>.md` 时，不允许编辑源码

3. 使用 **SQLite** 作为事实层：
   - 数据库路径：`.ai/codegraph/codegraph.db`
   - schema 参考：`.agents/skills/code-impact-guardian/references/schema.sql`

4. 第一版只需要支持四类节点和五类直接边：
   - 节点：`file` `function` `test` `rule`
   - 边：`DEFINES` `CALLS` `IMPORTS` `COVERS` `GOVERNS`

5. 第一版只存 **直接边**
   - 不要把间接传播写死到数据库里
   - 间接影响在生成报告时通过递归查询临时计算

6. 生成影响报告：
   - 路径：`.ai/codegraph/reports/impact-<task-id>.md`
   - 同时生成 Mermaid：
     `.ai/codegraph/reports/impact-<task-id>.mmd`

7. 改完代码后必须：
   - 更新 SQLite 图谱
   - 更新或追加报告的 post-change note
   - 跑相关测试
   - 如果可用，导入 coverage 结果

# 必须实现的文件

请优先实现并保证这些文件可用：

- `AGENTS.md`
- `.agents/skills/code-impact-guardian/SKILL.md`
- `.agents/skills/code-impact-guardian/agents/openai.yaml`
- `.agents/skills/code-impact-guardian/assets/codegraph-config.yaml`
- `.agents/skills/code-impact-guardian/assets/impact-report-template.md`
- `.agents/skills/code-impact-guardian/references/schema.sql`
- `.agents/skills/code-impact-guardian/scripts/init_db.py`
- `.agents/skills/code-impact-guardian/scripts/build_graph.py`
- `.agents/skills/code-impact-guardian/scripts/generate_report.py`
- `.agents/skills/code-impact-guardian/scripts/update_after_edit.py`

# build_graph.py 的要求

请不要只做空壳。请尽量实现一个能运行的第一版：

- 支持 Python / JavaScript(TypeScript) / Go
- 优先使用 Tree-sitter 做解析
- 如果某语言的 Tree-sitter 实现暂时不完整，可以先写清楚 fallback 行为
- 至少完成：
  - file 节点抽取
  - function 节点抽取
  - file -> function 的 `DEFINES`
  - function -> function 的 `CALLS`（能做多少做多少）
  - import 关系的 `IMPORTS`
- 证据写入 `evidence` 表
- 每条关键边尽量带：
  - repo
  - git_sha
  - path
  - start_line
  - end_line
  - source_type
  - permalink（如果仓库在 GitHub 上）

# generate_report.py 的要求

请实现一个可运行版本：

- 输入：
  - `--task-id`
  - `--seed`（node id）
  - `--max-depth`
- 输出：
  - Markdown 报告
  - Mermaid 图
- 内容至少包含：
  - task_id
  - git_sha
  - seed
  - direct neighbors
  - transitive paths
  - related tests
  - related rules
  - risk summary
  - evidence section

# GitHub 集成要求

请把 GitHub 功能当成“证据层”，不要当主数据库：

- code navigation：用于人工复核 definition / reference
- permalink：用于保存关键行范围证据
- blame：用于定位关键行最后修改者和 commit
- dependency graph：只用于包依赖上下文，不当作函数级调用图

如果仓库 remote 是 GitHub：
- 自动识别 repo URL
- 获取当前 git SHA
- 为 evidence 记录生成 GitHub 可回跳链接

# 约束

- 先保证流程闭环，再追求智能
- 先保证 SQLite schema 稳定，再增加 edge types
- 先保证 impact report 一定产生，再优化图谱准确率
- 如果某个功能暂时做不到，请明确标注 TODO 和 fallback
- 不要 silently skip 步骤
- 每个脚本都要能单独运行并打印清晰日志

# 交付物

请最终给我：

1. 新增和修改的文件清单
2. 每个脚本如何运行
3. 一次完整的 demo：
   - init db
   - build graph
   - generate report
4. 当前已完成能力
5. 当前未完成能力
6. 下一步建议
