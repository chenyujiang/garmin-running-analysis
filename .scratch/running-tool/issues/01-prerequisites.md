# 01: 实施前提：工具链与凭据就位

**What to build:** 本机具备编译导入 CLI 的条件，凭据放到数据目录下，后面的 ticket 不再需要人工准备环境。这是 HITL ticket：安装需要管理员权限，凭据只能由用户自己移动。

**Blocked by:** None (can start immediately)

**Status:** done

来源：[实施 spec](../spec.md) 的 Further Notes。

- [x] 用户安装 rustup stable，工具链为 `x86_64-pc-windows-msvc`
- [x] 用户安装 Visual Studio Build Tools，并勾选 C++ 工作负载
- [x] 一个临时的空 crate 能用 bundled feature 编译 `rusqlite`，验证完删除
- [x] 数据目录（`RUNNING_DATA_DIR`，默认 `%USERPROFILE%\running-data`）已创建，下面有 `secrets/`
- [x] 用户自己把 Personal API key 从仓库根目录的 `.env` 移成 `secrets/personal_api.key`，把 garminconnect 的 token 从 `~/.garminconnect` 移进 `secrets/garminconnect/`
- [x] 仓库根目录不再有 `.env`
- [x] agent 全程不读取、不打印任何 key 或 token 的内容，只检查文件是否存在
