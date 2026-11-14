# SpektraLab WebUI（fnOS app）

把无界面的引擎宿主变成一个完整的网页应用：在浏览器里浏览 NAS 上的照片、选胶片与相纸、调参渲染、导出。两条交付路径：

- **fnOS app（fpk）**：统一网关接入（`/app/spektralab-fnos`，NAS 登录态校验 + 用户 Header），文件授权走 [飞牛开放 API](https://developer.fnnas.com/api/overview/)；
- **独立 Docker**：任意有 Docker 的机器，`SPEKTRALAB_PHOTOS_ROOTS` 指定照片目录。

## 架构

```
浏览器 ── HTTP/SSE ──► bridge.py（容器内 python3，纯标准库）
                        ├── 托管 spektralab-host 子进程（stdio 二进制帧协议，
                        │     HOST-PROTOCOL.md，帧格式原样透传）
                        ├── 文件 API：列出/授权根目录、sidecar、设置存储、上传 inbox
                        │     （fnOS 模式下经 trim API + checkUserACL 逐用户鉴权）
                        └── 静态文件：vite 构建的前端（上游 desktop/ + overlay）
```

前端**复用上游 React 界面**（不是重写）：上游本就有 `Transport`/`Platform` 双抽象，overlay 只加两个实现（`bridgeTransport` / `bridgePlatform`）和四个新文件，`build-webui.sh` 打补丁的只有接线处（`main.tsx`、`host/client.ts`、`platform/index.ts`、`transport.ts` 的 kind 联合类型）。所有 UI 组件、参数面板、画布着色器原样上游。

## fnOS 开放 API 集成（`fnos_trim.py`）

fnOS app 模式（`/var/run/trim_open_gateway_apiscope.socket` 存在 + `TRIM_API_TOKEN` 注入）自动启用：

| 能力 | 接口 | 用途 |
|---|---|---|
| 应用共享授权 | `trim.file.getSharedAccessibleFolders` | 管理员授权的照片根目录 |
| 用户个人授权 | `trim.file.getUserAccessibleFolders`（uid） | 当前用户授权的目录 |
| 文件权限检查 | `trim.file.checkUserACL`（uid, path） | 每次列出/读取/写入前逐用户校验——应用的授权永不越过用户自己的权限 |
| 路径转换 | `trim.file.convertPath` | `/vol1/...` → 「存储空间1/xxx 的文件/yyy」展示 |

Scope 声明（`config/resource` 的 `api-scope`）：`trim.file.sharedAccess` / `trim.file.userAccess` / `trim.file.userAcl` / `trim.file.path`。统一网关的用户身份取 `X-Trim-Userid` Header（网关已校验 NAS 登录态），绝不信任客户端传的 uid。

## 核显加速

引擎是 Vulkan 计算着色器。fnOS 的 Intel 核显（如 UHD 730）透传进容器后，Mesa ANV 直接枚举它，渲染从 CPU（lavapipe，几十秒/张）降到秒级：

- fpk：`config/privilege` 已声明 `join-groups: ["video", "render"]`；compose 声明 `devices: /dev/dri`；
- Docker：`docker run --device /dev/dri ...`；
- `SPEKTRALAB_DEVICE=<index>` 可指定 Vulkan 设备序号（默认自动：有核显用核显，没有则 lavapipe）。
- `/api/appinfo` 的 `gpu` 字段回报透传状态与当前活动设备名，前端诊断用。

## 构建

```bash
bash build.sh              # 引擎宿主（上游 pin、测试、glibc 门禁）——WebUI 的前置
bash webui/build-webui.sh  # 前端（overlay 补丁 + vite）→ WebUI 镜像 → 冒烟
bash webui/pack-fpk.sh     # 组装 fpk 项目（含镜像 tar），有 fnpack 则直接打包
```

产物：`dist/spektralab-fnos-webui-<version>.tar.gz`（docker load / compose 用）+ fpk 包。

## 独立 Docker 运行

```bash
docker load -i dist/spektralab-fnos-webui-<version>.tar.gz
docker run -d --name spektralab -p 8080:8080 \
  --device /dev/dri \
  -e SPEKTRALAB_PHOTOS_ROOTS=/vol1/1000/photo \
  -v /vol1/1000/photo:/photos \
  -v spektralab-data:/data \
  spektralab-fnos:webui-<version>
# 浏览器打开 http://<nas>:8080
```

`/data` 存设置与上传的 inbox（「从我的电脑打开」的文件先进这里，再走协议打开）。

## HTTP API（bridge.py，供前端与脚本）

| 端点 | 说明 |
|---|---|
| `POST /api/rpc` | 协议帧进、协议帧出（`u32 LE header_len` + `u32 LE payload_len` + JSON + 载荷原样） |
| `GET /api/events` | SSE：宿主事件帧（渲染进度等） |
| `GET /api/hello` / `/api/appinfo` | 缓存的 hello / 桥接与 GPU 状态 |
| `GET /api/fs/roots` · `/api/fs/list?path=` | 授权根目录 / 目录列表（含 ACL 门禁） |
| `PUT/GET /api/fs/sidecar` | 照片旁的 `.spektra.json` |
| `GET/PUT /api/store/<area>/<name>` | 设置存储（导出配方等） |
| `POST /api/fs/upload/{init,chunk,finish}` | 本地文件上传 inbox（分块，4MB/块） |
| `POST /api/host/restart` · `GET /api/diagnostics` | 宿主重启 / stderr 尾部 |

路径安全：所有照片路径先归一化（`realpath`）再校验在授权根内（拒绝 `..` 穿越），fnOS 模式再过用户 ACL；网关 unix socket 权限 0660。

## fpk 包结构（webui/fpk/）

```
manifest              appname=spektralab-fnos, service_port, gateway 入口
config/privilege      run-as=package + join-groups [video, render]（核显）
config/resource       api-scope + data-share(spektralab/exports) + docker-project
cmd/main              start/stop/status（网关 socket 就绪即 status 0）
app/ui/config         统一网关入口 /app/spektralab-fnos → app.sock
app/docker/           docker-compose.yaml + 镜像 tar（install_callback docker load）
```

## Roadmap（WebUI 部分）

- fpk 在真机 fnOS 上实测（fnpack 打包 → 应用中心安装 → 授权目录 → 渲染一张 RAW）；
- 核显透传实测（`/api/appinfo` 的 `gpu.active_device` 应从 llvmpipe 变为 UHD 730）；
- CI 已接入 webui 构建与 fpk staging（fnpack 打包需自备机器一条命令完成）；
- 渲染进度的 SSE 已通，前端进度条接入 `progress` 事件。

## 已验证（2026-11-15，本地 Docker，引擎镜像 0.1.0 + 桥接）

- `hello`：Vulkan 后端可用（llvmpipe CPU 兜底）；
- 上传 inbox（init/chunk/finish）→ `open` 256×256 TIFF ✓；
- `render` live：引擎 891ms，262144 字节 RGBA ✓；
- `set_params`（print_exposure）→ `reprint`：`reprinted=true, negative_was_cached=true`（印相侧增量渲染，负片缓存命中）✓，像素确实移动 ✓；
- `export_image` JPEG 写入 /data ✓；
- 路径门禁：未授权路径 403，授权根内正常 ✓；静态 UI、`/api/fs/*`、`/api/appinfo`、SSE 端点全通 ✓。
