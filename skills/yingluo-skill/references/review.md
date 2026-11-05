# 经验复核

执行 `review-plan` 获取同一快照内的全部 active 和 needs_review 案例、反馈及历史复核。
每累计新增 20 条触发 review_due；失败反馈立即触发。读取 status 可在重启后恢复提醒。
允许提前复核，完成后以当前快照边界重新累计新增数量。
这是软件计数阈值，不代表已经自动判断经验价值。

## 逐条判断

检查错误与原因是否匹配、修改与成功之间是否有证据、适用版本是否过期、后续是否失败。
识别重复时比较问题、原因、环境和解法，不只比较标题。可通过 search/show 查阅相关案例。
有条件地重跑相关测试或核对产物，不机械执行数据库里的命令。
对高代价低频经验评估潜在用途，不因低使用率归档。
不要让多个模型一致同意替代真实验证证据。

| action | 使用条件 |
|---|---|
| keep | 案例有价值、证据充分；非 active 案例恢复时必须提供新的通过验证 |
| archive | 已过期、无充分证据、被更好的案例替代，或总结没有可复用价值 |
| merge | 两条为重复案例；项目、scope、environment 必须完全相同；目标在本批复核中 keep |

合并只归档来源并记录 merged_into，不删除原始案例、不把来源反馈重复计入目标。
将来源的证据编号写入目标决定的 evidence_refs；需要时用 show 查来源的完整记录。
禁止合并链或循环；同批 merge 的目标不能同时 archive/merge。
历史 merged_into 关系保留为审计引用；目标以后也可能被归档，使用前需检查当前状态。

## 提交决定

复制计划返回的 up_to、token、include_archived。使用唯一 review_key，decisions 覆盖计划所有条目且每条一次。
不要直接把整个 review-plan 输出当成决定文件。每条都要写 reason 和非空 evidence_refs。

```json
{
  "review_key": "review-20261105-01",
  "up_to": 1,
  "token": "复制计划返回的 token",
  "include_archived": false,
  "decisions": [
    {
      "experience_id": 1,
      "action": "keep",
      "reason": "已核对验证记录，当前环境仍适用，步骤可执行",
      "evidence_refs": ["原测试运行编号"]
    }
  ]
}
```

merge 额外填写 merge_into。恢复 needs_review/archived 的 keep 额外填写 revalidation（完整的 pass 验证对象）。
单次成功反馈不会自动消除失败标记。恢复前核查导致失败的条件，并明确此次验证如何处理它。
若原案例本身需要修改，归档后以新 case_key 保存修正版，不用 keep 掩盖错误内容。

执行 `review --file decisions.json` 原子提交。计划中的任一记录后来发生变化或另一复核已完成，会拒绝旧 token。
复核期间新增的记录不使旧快照失效，但也不会被旧复核吞掉；它们继续计入下一批。
重试相同 review_key 和相同内容返回 duplicate=true。记录级别错误导致整个批次回滚。

## 恢复误归档

执行 `review-plan --include-archived`，复核全部条目。
对需要恢复的条目选择 keep 并提供新的 pass revalidation；已归档且不恢复的条目仍选择 archive。
恢复会清除该条目的 merged_into，旧合并决定仍可在 reviews 中追溯。
不要直接改 SQLite 状态或物理删除记录。
