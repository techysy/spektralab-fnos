# spektralab-fnos

[SpektraLab](https://github.com/JamesQiu2005/SpektraLab) 渲染引擎的 fnOS（飞牛 NAS）交付：把 `spektralab-host`——按物理过程建模的胶片暗房引擎——打包成 Docker 镜像，在无 GPU 的 NAS 上通过 Mesa lavapipe（CPU Vulkan）渲染。

**这是什么**：无界面的引擎宿主。它通过 stdin/stdout 说 [上游 HOST-PROTOCOL](https://github.com/JamesQiu2005/SpektraLab/blob/main/desktop/HOST-PROTOCOL.md) 定义的二进制帧 JSON-RPC（`hello` / 渲染 RAW / 胶片模拟 / 导出 TIFF 等 24 个方法），给上层 UI 或脚本调用。

**这不是什么**：不是图形应用。上游的 Tauri 桌面版需要显示环境（WebKitGTK + X11/Wayland），不适合无头 NAS；fnOS 应用商店的 fpk 打包在 Roadmap 里。

## 在 fnOS 上使用

```bash
# 导入镜像（fnOS 的 Docker 管理界面，或 SSH）
docker load -i spektralab-fnos-<version>.tar.gz

# 冒烟：宿主应以一帧 JSON 应答 hello
echo '{"id":1,"method":"hello","params":{}}' | docker run -i --rm spektralab-fnos:<version>
```

上层调用按帧协议（`u32 LE header_len` + `u32 LE payload_len` + JSON + 二进制载荷）通信。性能参考：CPU（lavapipe）渲染一张全尺寸照片约几十秒；NAS 若有受支持的核显，设备透传进容器可大幅提速。

## 本地构建

任意装了 Docker 的机器：

```bash
bash build.sh          # 全流程：克隆上游 pin → 容器构建 → 测试 → 镜像 → 冒烟 → 打包
bash build.sh --skip-build   # 只重打镜像与产物
```

流程与门禁（脚本内固化）：

1. 克隆上游 [SpektraLab](https://github.com/JamesQiu2005/SpektraLab) 并检出 `UPSTREAM_PIN` 指定的 commit（当前 `1952c63`，v2.3.2）；
2. `debian:12` 容器内 `engine/build-linux.sh --test`（gcc 12、CMake/Ninja、glslang，**14 项 CTest 于 lavapipe** + 宿主冒烟）；
3. **glibc 门禁**：产物最高 GLIBC 符号需求必须 ≤ 2.36——fnOS 基于 Debian 12，上游 CI 的 Ubuntu 24.04 二进制（glibc 2.39）在 fnOS 上跑不起来，这正是本项目存在的理由；
4. 组装运行时镜像（引擎宿主 + 全部资源 + Mesa lavapipe，603MB → 压缩约 150MB）；
5. 镜像内协议冒烟（`hello` 应答 `backend.available: true`）；
6. 产出 `dist/`：镜像 tar.gz + 裸宿主 tar.gz + SHA256SUMS。

可选加速：把已校验的 `LibRaw-0.22.2.zip` 放进 `deps-seed/`（容器内会重新校验哈希）。

## 更新上游版本

改 `UPSTREAM_PIN` 为新 commit，重跑 `build.sh`。所有测试与门禁会重新执行。

## Roadmap

- **fpk 打包**：fnOS 应用商店的 fpk 格式（待做）；
- CI：GitHub Actions 上跑同一 `build.sh`，tag 自动发 Release；
- HTTP/WebSocket 桥：给网页前端当常驻服务（当前协议是 stdio，需要一层薄封装）。

## 许可

- 宿主与引擎：GPL-3.0-or-later（对应源码 = `UPSTREAM_PIN` 指向的上游检出；本仓库只含构建/打包脚本与镜像定义）。
- 胶片/相纸配置与放大 LUT：CC BY-SA 4.0（spektrafilm）。
- LibRaw：LGPL-2.1；Vulkan-Headers：Apache-2.0 OR MIT；stb：公有领域/MIT；volk：MIT。
- 派生关系与细节见上游 [license/NOTICE.md](https://github.com/JamesQiu2005/SpektraLab/blob/main/license/NOTICE.md)；镜像内 `licenses/` 随包齐全。
