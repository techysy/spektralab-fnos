<div align="center">

<img src="webui/fpk/app/ui/images/icon_256.png" width="96" alt="SpektraLab for fnOS">

# SpektraLab for fnOS

**把 SpektraLab 胶片暗房引擎装成飞牛 fnOS 原生应用：RAW 进、胶片模拟 + 放大印相出，核显加速，浏览器直接用**

[![Release](https://img.shields.io/github/v/release/techysy/spektralab-fnos?label=%E7%89%88%E6%9C%AC&color=2563eb)](https://github.com/techysy/spektralab-fnos/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/techysy/spektralab-fnos/total?label=%E4%B8%8B%E8%BD%BD&color=16a34a)](https://github.com/techysy/spektralab-fnos/releases)
[![Platform](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-%E9%A3%9E%E7%89%9B%20fnOS%20%28x86%29-6b7280)](#下载)
[![Upstream](https://img.shields.io/badge/%E4%B8%8A%E6%B8%B8-SpektraLab-4d6bfe)](https://github.com/JamesQiu2005/SpektraLab)
[![Vulkan](https://img.shields.io/badge/%E6%B8%B2%E6%9F%93-Vulkan%20%28ANV%20%7C%20lavapipe%29-a91e4e)](#性能)
[![License](https://img.shields.io/badge/%E8%AE%B8%E5%8F%AF-GPL--3.0--or--later-f59e0b)](LICENSE)

[下载](#下载) · [功能](#功能) · [快速开始](#快速开始) · [性能](#性能) · [架构](#架构) · [配置](#配置) · [更新日志](CHANGELOG.md)

</div>

上游项目：[JamesQiu2005/SpektraLab](https://github.com/JamesQiu2005/SpektraLab)（按物理过程建模的胶片暗房引擎）。本仓库不 fork 上游代码，只负责 fpk 打包、fnOS 生命周期脚本、HTTP 桥接（`webui/bridge`）与前端 overlay；引擎二进制一律由 `UPSTREAM_PIN` 指向的上游检出门禁构建（debian:12 容器 + 14 项 CTest + glibc 2.36 门禁）。

## 下载

从 [**Releases**](https://github.com/techysy/spektralab-fnos/releases/latest) 下载对应变体的 fpk：

| 文件 | 说明 |
| --- | --- |
| `SpektraLab-FnOS-<版本>-window-x86.fpk` | **推荐**：fnOS 统一网关窗口（NAS 登录态 + 逐用户 ACL），走 `/app/spektralab` |
| `SpektraLab-FnOS-<版本>-tab-x86.fpk` | 浏览器新标签页直连 8777 |
| `spektralab-fnos-<版本>-docker-webui.tar.gz` | 独立 Docker 镜像（非 fnOS 场景），`docker load` 使用 |
| `SHA256SUMS` | 以上全部资产的校验和 |

> 两个 fpk 变体同 appname、同数据区，安装其一即可互相切换；版本号严格对齐 `VERSION` 文件。
> 引擎宿主不在 Release 单独发布——它随 fpk 内部携带（CI 的 payload artifact 里有裸 bundle 供调试）。

## 架构

```
浏览器（上游 React UI + overlay）
   │  HTTP: POST /api/rpc（协议帧透传）+ GET /api/events（SSE 进度）+ 文件 API
   ▼
bridge.py（python3 纯标准库，包用户原生运行）
   ├── spektralab-host 子进程（stdio 二进制帧 JSON-RPC，24 个方法）
   │     └── Vulkan 渲染：核显直通 Mesa ANV / 无核显回退 lavapipe
   ├── 文件：授权目录浏览 / sidecar / 设置存储 / 上传 inbox（2 GiB 上限 + 磁盘水位）
   └── fnOS 模式：trim 开放 API（授权目录 + checkUserACL 逐用户鉴权）
```

详见 [WEBUI.md](WEBUI.md)；fpk 打包与 fnOS 生命周期的完整踩坑实录见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

## 功能

**fnOS 原生集成**
- **无 Docker**：引擎宿主与桥接以包用户身份直接运行（`run-as: package`，`video`/`render` 组）
- **统一网关**：window 变体经 `/app/spektralab` 接入，NAS 登录态校验 + 网关注入的用户 Header 逐用户鉴权
- **授权目录**：应用设置里勾选照片文件夹（trim 文件 API），照片根目录语义路径转换、导出目录开放共享（`@appshare/spektralab/exports`）
- **核显直通**：`/dev/dri` 透传 Mesa ANV 渲染（Intel UHD 730 实测），无核显自动回退 lavapipe（CPU）

**暗房流程**
- RAW 进（LibRaw 全家桶格式）→ 胶片模拟（spektrafilm 物理建模 profile）→ 放大印相（相纸 / 曝光 / 滤镜包 / Curve）→ 出（TIFF16 / JPEG / PNG / `.cube` LUT）
- sidecar 参数（`<照片>.spektra.json`）随照片保存，重开即还原
- 渲染三档：live（拖滑块 1600px）→ preview（3400px）→ full（全尺寸），进度经 SSE 实时推送

**安全边界**
- 每个照片路径夹紧到授权根目录（realtime 防穿越）+ fnOS 模式逐用户 ACL；RPC 方法级 path 门禁（open/export/write_image 分别 read/write 校验）
- 上传 inbox：单文件 2 GiB 上限、数据卷剩余 <2 GiB 拒收、文件名 basename 化 + 扩展名白名单

## 快速开始

### 安装

1. 从 [Releases](https://github.com/techysy/spektralab-fnos/releases/latest) 下载 fpk（推荐 window 变体）
2. 飞牛 App Center → **手动安装** → 选择 fpk 文件
3. 应用设置 → **授权目录**：勾选照片所在的文件夹
4. 桌面出现 **SpektraLab** 图标，点击打开（window 走网关 / tab 直连 8777）
5. 浏览器里选照片 → 选胶片/相纸 → 调参 → 导出（导出文件在应用数据区 `inbox/` 与 `@appshare/spektralab/exports`）

### 独立 Docker（非 fnOS 场景）

```bash
docker load -i spektralab-fnos-<版本>-docker-webui.tar.gz
docker run -d --name spektralab -p 8777:8080 \
  --device /dev/dri \
  -e SPEKTRALAB_PHOTOS_ROOTS=/photos \
  -v /vol1/1000/photo:/photos:ro \
  -v spektralab-data:/data \
  spektralab-fnos:webui-<版本>
# 浏览器打开 http://<nas-ip>:8777
```

### 从源码构建

```bash
bash build.sh               # 引擎宿主：上游 pin → debian:12 构建 → 14 项 CTest(lavapipe) → glibc 门禁 → 镜像
bash webui/build-webui.sh   # WebUI：前端 overlay + vite → 镜像 → 冒烟
bash webui/pack-fpk.sh      # fpk 项目组装（NAS 上 fnpack build 出 .fpk）
```

CI（`.github/workflows/fnos.yml`）跑同一条链：镜像构建 + 双变体 fpk（fnpack 1.2.1 pin + SHA256）+ tag `v*` 自动发 Release；fpk 项目打包前过 manifest 硬校验（appname 钉死 / 版本一致 / desc 单前缀 / wizard 非空 / 生命周期脚本语法）。

### 升级上游

改 `UPSTREAM_PIN` 为新 commit → push → CI 全门禁重建 → tag `v*` 发 Release。fpk 重打包只需 NAS 上 `fnpack build`。

## 性能

Intel UHD Graphics 730（ADL-S）实测，Sony A7M2 24MP RAW：

| 操作 | 耗时 |
|---|---|
| RAW 解码（首次打开，一次性） | ~7s |
| live 渲染（拖滑块，1600px） | **0.9s** |
| preview 渲染（3400px） | 1.6s |
| full 渲染（6024px 全尺寸） | **4.6s** |
| print 侧调参（reprint，负片缓存命中） | 更快 |

无核显时回落 lavapipe（CPU），全尺寸约几十秒。

## 配置

### 照片目录（授权目录）

- 安装后在 **应用设置 → 授权目录** 勾选照片所在文件夹（fnOS trim API，逐用户 ACL 生效）
- 应用内照片只读；导出写入应用数据区，经 `@appshare/spektralab/exports` 共享目录可直接从飞牛文件管理器取
- 独立 Docker 模式由 `SPEKTRALAB_PHOTOS_ROOTS` 指定（`;` 分隔多个根）

### 核显 / 渲染设备

- fnOS 自带 mesa-vulkan-drivers，包用户已在 `video`/`render` 组；`/dev/dri` 由 fnOS 透传
- `SPEKTRALAB_DEVICE` 可指定 Vulkan 设备序号（0 起始）；留空取 Vulkan 枚举第一个（无核显机器即 lavapipe，行为正确）

### 端口与数据区

- **端口**：8777（manifest `service_port`，tab 变体与 Docker 模式直连）
- **应用数据**：`/vol{n}/@appdata/spektralab/`（设置存储 store/、上传 inbox/、日志、pid）
- **导出共享**：`/vol{n}/@appshare/spektralab/exports/`（config/resource 的 data-share 声明）

### bridge 环境变量（Docker 模式）

| 变量 | 说明 | 默认 |
|---|---|---|
| `SPEKTRALAB_HOST_BIN` | 宿主二进制路径 | `/opt/spektralab/spektralab-host` |
| `SPEKTRALAB_RESOURCES` | 引擎资源目录 | `/opt/spektralab/engine` |
| `SPEKTRALAB_PHOTOS_ROOTS` | 授权照片根目录（`;` 分隔） | 无（仅数据区可写） |
| `SPEKTRALAB_FNOS_PORT` | HTTP 端口 | `8080`（`0` = 禁用） |
| `SPEKTRALAB_FNOS_SOCKET` | 额外监听的 unix socket（fnOS 网关） | 无 |
| `SPEKTRALAB_DEVICE` | Vulkan 设备序号 | 空（自动） |

## 项目结构

```
spektralab-fnos/
├── build.sh                     引擎宿主全链构建：上游 pin → debian:12 → CTest → glibc 门禁 → 无头镜像
├── docker/Dockerfile            无头运行镜像 + smoke_hello.py 协议冒烟
├── UPSTREAM_PIN · VERSION       上游锁定 commit 与 fpk 版本号（manifest version 必须与之一致）
├── deps-seed/                   LibRaw 离线种子（弱网构建用；runner 上容器自取）
├── upstream/                    上游检出（pin 溯源；构建产物 upstream/build/ 不入库）
├── webui/
│   ├── bridge/
│   │   ├── bridge.py            HTTP 前端：协议帧透传 + SSE + 文件 API + 上传配额 + 路径夹紧
│   │   ├── fnos_trim.py         fnOS 开放 API 客户端（unix socket + TRIM_API_TOKEN）
│   │   └── healthcheck.py       容器健康检查
│   ├── frontend/                上游 desktop 前端 + overlay（vite 构建 → dist/）
│   ├── docker/Dockerfile.webui  WebUI 镜像（引擎 bundle + bridge + www）
│   ├── fpk/                     fpk 模板：manifest · config（privilege/resource）· cmd 生命周期 · ui 入口 · wizard
│   ├── pack-fpk.sh              fpk 项目组装（变体选择 + desc 前缀 + payload 装载）
│   └── build-webui.sh           WebUI 全链构建（前端 → 镜像 → 冒烟）
├── .github/workflows/fnos.yml   CI：镜像 + 双变体 fpk（fnpack pin + manifest 门禁）+ Release
├── NOTICE.md · LICENSE          许可：GPL-3.0-or-later（上游组件许可见 NOTICE）
└── TROUBLESHOOTING.md · WEBUI.md  踩坑实录 / WebUI 与桥接协议文档
```

<details>
<summary><b>开发者：CI 与 fpk 打包</b></summary>

CI（`fnos.yml`）三个 job：

1. **build** — `build.sh` + `build-webui.sh`（引擎门禁 + 镜像 + 冒烟），产出 images 与 payload artifacts
2. **fpk** — 双变体矩阵：下载 payload → `pack-fpk.sh` 组装 → **manifest 硬校验**（必需字段 / appname=spektralab / 版本=VERSION / desc 单【】前缀 / wizard 非空（10111 坑）/ 生命周期脚本 bash -n）→ fnpack 1.2.1（SHA256 pin）→ `SpektraLab-FnOS-<版本>-<变体>-x86.fpk`
3. **release** — tag `v*` 触发：合并 SHA256SUMS → 资产上传（--clobber 幂等）

产物命名统一：`SpektraLab-FnOS-<版本>-<变体>-x86.fpk` · `spektralab-fnos-<版本>-docker-webui.tar.gz` · 单一 `SHA256SUMS`（无裸宿主 bundle——它随 fpk 内部携带）。

</details>

## 文档

- [WEBUI.md](WEBUI.md) — WebUI 与桥接协议：端点、帧格式、fnOS 模式鉴权链
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — fpk 打包与 fnOS 生命周期踩坑实录（10111 / 10238 / 组解析 / 网关前缀等）
- [NOTICE.md](NOTICE.md) — 许可与派生关系（GPL-3.0 / CC BY-SA / LGPL / MIT 对应组件）
- 上游 [HOST-PROTOCOL](https://github.com/JamesQiu2005/SpektraLab/blob/main/desktop/HOST-PROTOCOL.md) — 引擎线协议（24 个方法）

## 已知限制

- 仅 x86（引擎构建与 fnpack 链未覆盖 ARM；fnOS ARM 设备不可用）
- 无核显时 full 渲染回落 lavapipe（CPU），全尺寸约几十秒——适合单张精修，不适合批量
- 照片目录应用内只读，导出走应用数据区（受授权目录与 ACL 约束）
- 信任面依赖 fnOS 统一网关（window）或局域网可达性（tab / Docker 直连 8777），无内置 HTTPS；请经 fnOS 网关或受信任网络使用
- 上游仍是活跃开发中的项目（引擎协议 / 前端可能变化），升级 pin 后 CI 全门禁重跑是唯一保障

## 许可证

- 宿主与引擎：GPL-3.0-or-later（对应源码 = `UPSTREAM_PIN` 指向的上游检出；本仓库只含构建/打包/桥接代码，同为 GPL-3.0-or-later）
- 胶片/相纸配置与放大 LUT：CC BY-SA 4.0（spektrafilm）
- LibRaw：LGPL-2.1；Vulkan-Headers：Apache-2.0 OR MIT；stb：公有领域/MIT；volk：MIT
- 派生关系与细节见 [NOTICE.md](NOTICE.md)
