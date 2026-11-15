# spektralab-fnos

> SpektraLab — 按物理过程建模的胶片暗房引擎：RAW 进，胶片模拟 + 放大印相出。跑在你的飞牛 NAS 上，核显加速，浏览器直接用。
>
> SpektraLab — a physics-modeled film darkroom engine: RAW in, film simulation + enlarger printing out. Runs on your fnOS NAS with iGPU acceleration, right in the browser.

将 [JamesQiu2005/SpektraLab](https://github.com/JamesQiu2005/SpektraLab) 的引擎宿主打包为飞牛 NAS (fnOS) 应用：无 GPU 的 NAS 通过 Mesa lavapipe（CPU Vulkan）渲染；有核显（Intel UHD 730 实测）则透传 `/dev/dri` 由 Mesa ANV 直接渲染。

---

## 它是什么 / What it is

- **引擎宿主**：`spektralab-host`，无界面，stdio 二进制帧 JSON-RPC（[HOST-PROTOCOL](https://github.com/JamesQiu2005/SpektraLab/blob/main/desktop/HOST-PROTOCOL.md)，24 个方法：open / render / set_params / export 等）
- **桥接服务**：`webui/bridge/bridge.py`（纯标准库 Python）——托管宿主进程，HTTP 透传协议帧 + SSE 进度事件 + 文件 API
- **WebUI**：复用上游 React 界面（overlay 注入桥接传输层），完整编辑器：胶片/相纸选择、曝光与滤镜包、Curve、导出 TIFF16/JPEG/PNG/.cube
- **fnOS app**：fpk 打包，App Center 安装，桌面图标直开

## 快速开始 / Quick Start

### 方式一：使用 Release（推荐） / Option 1: Release

1. 从 [Releases](https://github.com/techysy/spektralab-fnos/releases) 下载 `spektralab-fnos.fpk`（或 CI artifact 里的 `spektralab-fnos-fpk-project` 自行 `fnpack build`）
2. 飞牛 App Center → **手动安装** → 选择 fpk 文件
3. 应用设置 → **授权目录**：勾选照片所在的文件夹
4. 桌面出现 **SpektraLab** 图标，点击打开（端口 8777）
5. 浏览器里选照片 → 选胶片/相纸 → 调参 → 导出

### 方式二：独立 Docker（无 fpk） / Option 2: plain Docker

```bash
docker load -i dist/spektralab-fnos-webui-<version>.tar.gz
docker run -d --name spektralab -p 8777:8080 \
  --device /dev/dri \
  -e SPEKTRALAB_PHOTOS_ROOTS=/photos \
  -v /vol1/1000/photo:/photos:ro \
  -v spektralab-data:/data \
  spektralab-fnos:webui-<version>
# 浏览器打开 http://<nas-ip>:8777
```

### 从源码构建 / Build from Source

```bash
bash build.sh               # 引擎宿主：上游 pin → debian:12 构建 → 14 项 CTest(lavapipe) → glibc 门禁 → 镜像
bash webui/build-webui.sh   # WebUI：前端 overlay + vite → 镜像 → 冒烟
bash webui/pack-fpk.sh      # fpk 项目组装（NAS 上 fnpack build 出 .fpk）
```

## 端口与数据 / Port & Data

- **端口**：8777（manifest `service_port`，浏览器直连）
- **应用数据**：`/vol{n}/@appdata/spektralab-fnos/`（设置存储、上传 inbox、导出文件）
- **照片目录**：应用内只读（导出写入应用数据目录）；独立 Docker 模式由 `SPEKTRALAB_PHOTOS_ROOTS` 指定
- **核显**：`/dev/dri` 透传 + `video`/`render` 组；`SPEKTRALAB_DEVICE` 可指定 Vulkan 设备序号

## 性能参考 / Performance

Intel UHD Graphics 730（ADL-S）实测，Sony A7M2 24MP RAW：

| 操作 | 耗时 |
|---|---|
| RAW 解码（首次打开，一次性） | ~7s |
| live 渲染（拖滑块，1600px） | **0.9s** |
| preview 渲染（3400px） | 1.6s |
| full 渲染（6024px 全尺寸） | **4.6s** |
| print 侧调参（reprint，负片缓存命中） | 更快 |

无核显时回落 lavapipe（CPU），全尺寸约几十秒。

## 架构 / Architecture

```
浏览器（上游 React UI + overlay）
   │  HTTP: POST /api/rpc（协议帧透传）+ SSE 进度 + 文件 API
   ▼
bridge.py（python3 标准库）
   ├── spektralab-host 子进程（stdio 帧）
   ├── 文件：授权目录浏览 / sidecar / 设置 / 上传 inbox
   └── fnOS 模式：trim 开放 API（授权目录 + checkUserACL 逐用户鉴权）
```

详见 [WEBUI.md](WEBUI.md)。

## 踩坑记录 / Pitfalls

详见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)（fpk 打包与 fnOS 生命周期的完整坑录）。

## 更新上游 / Upstream updates

改 `UPSTREAM_PIN` 为新 commit → push → CI 重建（全部测试与门禁重跑）→ tag `v*` 发 Release。fpk 重打包只需 NAS 上 `fnpack build`。

## 相关链接 / Links

- [SpektraLab 上游](https://github.com/JamesQiu2005/SpektraLab) · [fnOS 开发者文档](https://developer.fnnas.com/docs/guide)
- [HOST-PROTOCOL](https://github.com/JamesQiu2005/SpektraLab/blob/main/desktop/HOST-PROTOCOL.md)（引擎线协议）

## 许可 / License

- 宿主与引擎：GPL-3.0-or-later（对应源码 = `UPSTREAM_PIN` 指向的上游检出；本仓库只含构建/打包/桥接代码）
- 胶片/相纸配置与放大 LUT：CC BY-SA 4.0（spektrafilm）
- LibRaw：LGPL-2.1；Vulkan-Headers：Apache-2.0 OR MIT；stb：公有领域/MIT；volk：MIT
- 派生关系与细节见上游 [license/NOTICE.md](https://github.com/JamesQiu2005/SpektraLab/blob/main/license/NOTICE.md)
