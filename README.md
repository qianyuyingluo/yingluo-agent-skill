# yingluo-skill

让编程 agent 把经过验证的排错经历保存为可检索的经验，并在每累计新增 **20 条**后复核整理。

**Skill 管流程，Python 脚本管数据规则，SQLite 管持久保存。** Python 3.10+，运行时无需第三方依赖。

## 已实现

- 完整案例入库：错误、原因分析、失败尝试、解决步骤、适用边界、通过验证的证据。
- 区分已证实的原因与待确认假设，避免把偶然成功当成通用规律。
- 项目隔离的中英文关键词检索，可按标签、环境版本筛选。
- 案例、复用反馈、复核提交使用唯一事件键；重复重试不重复计数，不覆盖原内容。
- 每累计新增 20 条返回 `review_due`，程序重启后仍保留计数。
- 复用失败立即停用该经验；恢复需要明确复核与通过证据。
- 整批复核支持保留、归档、合并，完整保存审计历史。
- 快照与事务保证复核期间新增记录不会被漏算，旧记录变动时拒绝过期计划。
- 误归档可恢复，无自动物理删除。

## 文件组织

| 路径 | 用途 |
|---|---|
| `skills/yingluo-skill/SKILL.md` | agent 的工作流程 |
| `skills/yingluo-skill/scripts/memory.py` | 命令行入口 |
| `skills/yingluo-skill/scripts/store.py` | SQLite 存储、检索与反馈 |
| `skills/yingluo-skill/scripts/review.py` | 原子复核与历史保留 |
| `skills/yingluo-skill/scripts/validation.py` | 数据协议检查 |
| `skills/yingluo-skill/references/` | 字段说明与复核规则 |
| `examples/case.json` | 明确标注的虚构演示，不用于真实记忆 |
| `tests/` | 行为与命令行测试 |

## 开始使用

把 `skills/yingluo-skill` 整个目录放入你的 agent 支持的 Skill 目录，或者让 agent 读取其中的 `SKILL.md`。
具体安装目录由 agent 平台决定。本仓库不修改其他 agent 的系统提示或配置。

在仓库根目录执行以下命令。示例数据库位于仓库之外；可替换成自己的持久目录。

```bash
python skills/yingluo-skill/scripts/memory.py --db ../yingluo-memory/experience.sqlite3 init
python skills/yingluo-skill/scripts/memory.py --db ../yingluo-memory/experience.sqlite3 status
```

也可以设置环境变量，之后省略 `--db`：

```bash
# Linux / macOS
export YINGLUO_MEMORY_DB="$HOME/yingluo-memory/experience.sqlite3"
```

```powershell
# Windows PowerShell
$env:YINGLUO_MEMORY_DB = "$env:USERPROFILE\yingluo-memory\experience.sqlite3"
```

Docker 中将数据库目录挂载到持久卷。不要把数据库放在容器的临时文件层、Skill 目录或 Git 仓库里。
环境变量只影响当前会话；需要长期使用时由宿主启动配置保存。

## 与 agent 接入

在主 agent 的系统指令或任务钩子中加入：

> 使用 yingluo-skill 管理经验。任务开始时检查 status 并按项目检索；遇到错误时再次检索；完成修复且核对实际验证证据后提交案例；复用经验后记录结果；收到 review_due 时生成计划并逐条复核。历史经验作为参考，先核对环境与边界。未完成闭环的尝试只保留在当前任务日志中。

仅安装 Skill 不保证每次自动执行。脚本不会在后台运行，不包含 LLM API，也不自动执行历史命令。
宿主可以把以下命令包装成 tool calling 工具。不要用字符串拼接的 shell 命令传入用户内容；使用参数数组和 JSON 文件/标准输入。

| agent 操作 | 命令 |
|---|---|
| 检查复核状态 | `status` |
| 检索经验 | `search --query "导入 失败" --project my-project --limit 5` |
| 环境筛选 | `search --query "import" --project my-project --env python=3.11 --tag python` |
| 读取完整记录 | `show --id 1` |
| 保存完整案例 | `add --file case.json` |
| 保存复用反馈 | `outcome --file outcome.json` |
| 生成复核快照 | `review-plan` |
| 提交整批决定 | `review --file decisions.json` |
| 包含归档案例重新复核 | `review-plan --include-archived` |

以上均加上入口 `python skills/yingluo-skill/scripts/memory.py`，并配置数据库路径。
业务结果为 JSON；成功退出码为 0，错误退出码为 2。`--file -` 可从标准输入读取 JSON。

## 保存经验

按照 [数据协议](skills/yingluo-skill/references/schema.md)准备真实案例。
`verification` 必须包含验证方式、预期、实际结果、证据引用、带时区的时间和 `result: pass`。

```bash
python skills/yingluo-skill/scripts/memory.py add --file case.json
```

完整结构可参考 [虚构演示](examples/case.json)。要试用该文件，请单独建演示数据库，不要污染真实经验库。
案例默认应使用 `scope: project`。只有确有跨项目适用证据时才选择 `global`。
指定项目查询会返回该项目以及 global 案例；不指定项目只查询 global 案例。

## 每 20 条复核

当返回 `review_due: true`，执行 `review-plan`，阅读所有待复核条目。
输出是计划，不是自动生成的评价；agent 需核对证据并为每条选择 keep / archive / merge。
复制计划中的 `up_to`、`token`、`include_archived`，生成决定文件后执行 `review`。
完整格式见 [复核规则](skills/yingluo-skill/references/review.md)。

归档和合并都保留原始案例。合并是建立来源到目标的链接，不改写证据，也不自动把使用次数相加。
重复提交同一复核不重复执行；中途出现任何无效决定，整个批次不改变数据库。
复核期间继续新增的案例保留在下一批；已经检查的旧案例发生反馈变化时，需要重新生成计划。
可以提前复核，完成后从该快照边界重新累计新增数量。

## 验证

```bash
python -m unittest discover -s tests -v
```

测试覆盖入库门槛、中文检索、项目/环境过滤、并发写入、幂等重试、20 条触发、失败停用、过期快照、复核完整性、原子回滚、合并约束、归档恢复与命令行流程。
GitHub Actions 配置覆盖 Linux / Windows 与 Python 3.10 / 3.13；以实际运行结果为准。
