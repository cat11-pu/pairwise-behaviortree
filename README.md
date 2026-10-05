# btree

一个只依赖 Python 标准库的行为树运行时，用来给小型 AI 或任务调度编排决策流程。

## 目录

- `btree/core.py`：运行时本体。状态枚举 `Status`；实体节点 `Action`；组合节点 `Sequence`、`Selector`；装饰器 `Inverter`、`Succeeder`、`RepeatUntilFail`、`Cooldown`；层级黑板 `Blackboard`；每 tick 执行预算 `TickContext`；入口 `BehaviorTree`。
- `btree/__init__.py`：对外导出的名字。
- `tests/test_core.py`：unittest 用例，覆盖组合节点、装饰器、黑板、执行预算与复位。

## 环境

Python 3，纯标准库，不需要联网，也不需要安装任何第三方依赖。

## 跑测试

在项目根目录执行：

```
python3 -m unittest discover -s tests -v
```

Windows 上如果 `python3` 不在 PATH 里，把 `python3` 换成 `py -3` 或解释器的绝对路径。

只跑一个文件：

```
python3 -m unittest tests.test_core -v
```

只跑一个用例：

```
python3 -m unittest tests.test_core.CooldownTests -v
```
