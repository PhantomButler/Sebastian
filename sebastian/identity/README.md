# identity

> 上级索引：[sebastian/](../README.md)

## 模块职责

负责身份认证与权限管理。当前处于 **Phase 5 占位阶段**，`__init__.py` 为空模块；JWT 认证逻辑目前直接实现在 `sebastian/gateway/auth.py`。待 Phase 5 启动后，本模块将承接用户身份模型、角色权限、多用户受控访问等完整实现。

## 目录结构

```
identity/
└── __init__.py    # 占位入口，当前为空（Phase 5 未实现）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| JWT 签发与校验（当前实现位置） | [../gateway/auth.py](../gateway/auth.py) |
| 用户身份模型 / 权限角色（Phase 5） | 在本目录新建 `models.py`、`permissions.py` 等 |
| 多用户受控访问策略（Phase 5） | 在本目录新建 `access_control.py` |

---

> 修改本目录或模块后，请同步更新此 README。
