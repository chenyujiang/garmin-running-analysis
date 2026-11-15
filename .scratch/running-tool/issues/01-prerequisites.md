# 01: Prerequisites: toolchain and credentials in place

**What to build:** This machine can compile the import CLI, and the credentials sit in the data directory, so later tickets need no manual environment setup. This is a HITL ticket: the installs need administrator rights, and only the user may move the credentials.

**Blocked by:** None (can start immediately)

**Status:** done

Source: Further Notes in the [implementation spec](../spec.md).

- [x] The user installs rustup stable with the `x86_64-pc-windows-msvc` toolchain
- [x] The user installs Visual Studio Build Tools with the C++ workload
- [x] A throwaway empty crate compiles `rusqlite` with the bundled feature; it is deleted after the check
- [x] The data directory (`RUNNING_DATA_DIR`, default `%USERPROFILE%\running-data`) exists and has `secrets/` under it
- [x] The user moves the Personal API key from `.env` in the repository root to `secrets/personal_api.key`, and the garminconnect tokens from `~/.garminconnect` into `secrets/garminconnect/`
- [x] There is no `.env` left in the repository root
- [x] The agent never reads or prints the content of any key or token; it only checks that the files exist
