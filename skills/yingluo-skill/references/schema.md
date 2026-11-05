# 数据协议

所有输入使用 UTF-8 JSON，不允许未知字段、重复键或 NaN。列表只允许字符串。
案例是事实摘要，不包含私有思维链；不要保存密钥或不必要的原始日志。

## 案例：add --file case.json

| 字段 | 类型与要求 |
|---|---|
| case_key | 最长 200 字符的唯一事件标识，例如 project/task/error-1；重试保持不变 |
| title | 简短的问题标题，最长 200 字符 |
| project | 稳定项目标识，最长 200 字符 |
| scope | project 或 global；默认在编写案例时选 project |
| environment | 非空对象，键值均为字符串，例如 python、os、依赖版本 |
| tags | 字符串列表，可为空 |
| error | 可观察的错误、触发条件和修复前失败证据摘要 |
| cause | 原因分析及其证据；明确尚未确认的部分 |
| cause_status | confirmed 或 hypothesis；不能把修复成功当成根因已证实 |
| failed_attempts | 失败尝试及结果列表，没有额外失败尝试可为空 |
| solution | 非空的实际解决步骤列表 |
| boundaries | 非空的前提、限制、不适用条件列表 |
| verification | 以下验证对象，result 必须为 pass |

案例入库后内容不可原地改写。修正错误总结时归档旧案例，以新的 case_key 提交新案例，并在原因/边界中说明关系。
同一 case_key 内容完全相同会返回 duplicate=true；不同内容会拒绝，避免悄悄覆盖证据。
脚本不验证语义真实性。artifact_ref 是证据定位信息，不会被脚本读取或执行。

## 验证对象

```json
{
  "method": "实际运行的测试或人工验收方式",
  "expected": "事先确定的验收标准",
  "observed": "实际观察到的输出与行为",
  "artifact_ref": "持久日志位置、工具运行编号、CI 链接或人工验收记录编号",
  "verified_at": "2026-11-05T10:00:00+08:00",
  "result": "pass"
}
```

使用真实的验证时间和结果。成功验证为 pass，失败验证为 fail。
保留足以复查的引用，不要把易失的临时文件路径当成唯一长期证据。
时间必须含时区。confirmed 表示原因已获证据支持，不表示对所有环境都有效。

## 复用反馈：outcome --file outcome.json

必填 event_key（唯一）、experience_id（正整数）、result、notes。
result 可为 success / failure / inapplicable。
success 必须提供 verification.result=pass；failure 必须提供 verification.result=fail。
inapplicable 只填说明条件差异的 notes，不填 verification。
不同的实际复用必须使用不同 event_key；重试同一事件不重复计数。

## 数据库与检索

- experiences 保存案例，outcomes 保存复用反馈，reviews 保存复核决定，meta 保存 schema 版本和复核进度。
- active 可检索；needs_review 与 archived 不进入默认检索。
- `show --id N` 返回案例、全部复用反馈和相关复核决定。
- 查询采用中英文关键词子串匹配及标题加权，不是向量语义搜索；中文可用空格分隔关键词。
- 项目/标签/环境筛选是数据适用范围过滤，不是多用户安全隔离。不同用户应使用独立数据库或在宿主服务鉴权。
- 使用 SQLite 默认事务日志，写事务串行化并等待锁最多 10 秒。锁超时返回错误，宿主可用同一事件键重试。
- 运行时数据库不提交 Git；Skill 不提供云同步或网络服务。在线备份应使用 SQLite backup API，或关闭所有连接后备份文件。
