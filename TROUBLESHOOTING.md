# TROUBLESHOOTING — fpk 打包与 fnOS 生命周期踩坑录

真机（fnOS 1.2.x，x86）调通 SpektraLab fpk 过程中踩到的坑，按症状索引。适用于任何走 docker-project + 统一入口的 fnOS 应用。

## 安装阶段

### `[Error]Something wrong with appcenter: code 10111`（应用中心空指针）

**症状**：`install-fpk` 在 "Verifying files..." 后立刻 10111；服务端日志 `/var/log/trim_app_center/error.log` 出现 `runtime error: invalid memory address or nil pointer dereference, Data:(*vo.WizardData)(nil)`；**info 日志里没有 `install app` 记录**（任务根本没创建）。

**根因**：`wizard/install` 文件是空数组 `[]`（或目录、或非法 JSON）——应用中心的向导解析器对空表单解引用空指针。错误信息里的 `WizardData` 就是它。

**修复**：wizard 文件必须是**非空** JSON 表单数组，例如只有一条 tips：
```json
[{"stepTitle": "提示", "items": [{"type": "tips", "helpText": "..."}]}]
```
**注意**：构建脚本里任何"写默认 wizard"的逻辑都会在后续重打包时悄悄覆盖它——我们的 `pack-fpk.sh` 曾这样污染了五轮二分排查。排查包问题前，先解包 fpk 验证内容（fpk 是 tar.gz：`tar xzf x.fpk wizard/install`）。

### `code 10238` + `text="docker load failed"`（install 回滚）

**症状**：install 任务创建成功但 1 秒内回滚；`/var/log/apps/<app>.log` 见 `permission denied ... docker.sock`。

**根因**：`config/privilege` 为 `run-as: package` 时**生命周期脚本以包用户运行**，包用户不在 docker 组，连不上 `/var/run/docker.sock`。

**修复**：`join-groups` 加 `"docker"`；install_callback 里 `docker load` 失败时再查目标镜像是否已在本地（镜像已 pre-load 过就放行），双保险：
```json
{ "defaults": { "run-as": "package" }, "join-groups": ["video", "render", "docker"] }
```

### fpk 大文件

fpk 内任何文件超 GitHub/应用中心的限制前先想清楚：镜像 tar（~150MB）内嵌在 `app/docker/` 里可行（本地安装），但**不要**把构建产物提交进 git（GitHub 100MB 文件限制拒收 push）。

## 启动阶段

### `code 10500` / 容器停在 Created：`Unable to find group render: no matching entries in group file`

**症状**：compose 里 `group_add: [video, render]`，`docker create` 成功、**start 时**失败。`/etc/group` 里明明有 render。

**根因**：组名解析发生在容器 start 时 daemon 的一条路径上，fnOS 的 daemon 在该路径只查基础 group 文件（NSS 别名条目不可见）。

**修复**：compose 用 Debian 稳定数字 GID：
```yaml
group_add: ["44", "105"]   # video=44, render=105 (Debian 12)
```

### 框架 start 只 `docker start` 已有容器

appcenter 在 start 时**不会**重新 `compose up`；compose 配置变更后需强制重建（`docker compose up -d --force-recreate`，带 TRIM_APPDEST/TRIM_PKGVAR/TRIM_SERVICE_PORT 环境变量），否则容器沿用旧配置。compose 本身在**安装时**由框架拉起。

### `TRIM_APPDEST` 双路径

fnOS 版本差异：有的传 `/var/apps/<app>`，有的直接传 `/vol{n}/@appcenter/<app>`。cmd/main 一律 `${TRIM_APPDEST:-/var/apps/${TRIM_APPNAME}}` 兜底再 `readlink -f`（参考 9Router 的双路径兼容）。

## 入口阶段

### HTTPS 桌面里 iframe 打不开（点图标没反应）

fnOS 桌面走 nginx **HTTPS** 时，`type: iframe` + `protocol: http` 的入口是跨协议 iframe，浏览器混合内容策略直接拦截——iframe 空白，应用本身完全正常（curl 端口 200）。

**修复**：入口改 `type: url`（新标签页打开，顶级导航不受混合内容限制），与 9Router/MetaCubeXD 一致：
```json
{ "type": "url", "protocol": "http", "port": "8777", "url": "/" }
```
要留在 fnOS 桌面壳内（iframe）则必须走统一网关（`gatewayPrefix` + `gatewaySocket`，同域转发），前端需按子路径适配资源基址。

## 运行阶段

### 包用户写文件 / docker CLI

一切以包用户跑的脚本（含 `docker` CLI）都依赖 join-groups；组员变更在**重装**后生效（组关系在用户创建时绑定）。

### 应用日志位置

- 应用自身输出：`/var/log/apps/<appname>.log`（install/upgrade 回调的 stdout/stderr）
- 应用中心服务端：`/var/log/trim_app_center/{info,error}.log`
- 用户可见错误：生命周期脚本里写 `TRIM_TEMP_LOGFILE` 再非零退出

### 诊断命令速查

```bash
sudo /usr/local/bin/appcenter-cli status <app>          # 框架视角状态
sudo tail -20 /var/log/apps/<app>.log                    # 安装/升级回调输出
sudo grep 10111 /var/log/trim_app_center/error.log       # 服务端错误码
tar xzf app.fpk -O manifest                              # 解包验证 fpk 内容
```
