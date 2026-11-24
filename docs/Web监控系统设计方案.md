# 抽烟检测监控系统 Web 端设计方案（v0.5 · M1/M1.5/M2 已落地）

- 版本：v0.5（M1 基础设施、M1.5 工程独立、M2 在线推理引擎均已完成并实测；M3 待启动）
- 日期：2026-11-24
- 关联：《人工智能原理与实践-期末大作业》要求、任务 #14/#16/#20、三步方案第①步 W_full 稳定性验证
- **Web 工程根**：`C:\Users\YS\Desktop\Study\AI_Train\smoke-monitor-web`（Windows + dl-gpu / Python 3.10，自包含 `models/`、`samples/`）；训练基地为平级目录 `C:\Users\YS\Desktop\Study\AI_Train\smoke_detection`（仅离线训练 / 数据集 / runs，不再放 Web 运行代码）。

> **修订记录**
> - v0.2（2026-11-23，按评审追问更新）：① **视频源获取增强**：P0 在“样例下拉 + 摄像头”之外，新增**浏览器上传视频**与**本机路径直读**（新增 `source_resolver` 服务与 `resolve-local`/`upload` 两个接口）；多文件/文件夹**批量检测仍为 P1**。② **推理参数全部放前端可调**，并明确三级生效时机（下一帧即时生效 / 推理线程内安全应用 / 切换模型需重载，模型切换仍列 P1）；新增 `iou` 可调。③ Q1 投票默认值、Q2 默认样例视频**降级为不阻塞 M1**（默认先对齐磁盘现状，页面可随时调）。
> - v0.1（2026-11-23）：初版评审稿，确定 Flask + 原生 JS + MySQL 独立容器 + 投票 ALARM/10s 冷却事件记录 + P0 范围与 M1–M5 计划。
> - v0.3（2026-11-23 晚，M1 落地补丁）：见下方“v0.3 实现定稿补丁”A–E 节；**端口、参数生效时机、Q7 路径策略、.env 位置以补丁为准**，下文 v0.1/v0.2 正文将在 M2–M5 逐节合并修订。
> - v0.4（2026-11-23 深夜，M1.5 工程独立·方案 C）：Web 工程从训练基地整体迁至平级 **`smoke-monitor-web\`** 并做成自包含（3 个检测权重入 `models/`、2 个样例视频入 `samples/`）；**新启动目录、compose 管理目录、配置默认路径、M2 实现位置以下方 F 节为准**；MySQL 容器 / 命名卷 / 3307 与 Web 8010、浏览器地址均不变。
> - v0.5（2026-11-24，M2 在线推理引擎）：新增 `webapp/services/infer_engine.py`（检测+投票+绘制+JPEG 唯一实现）、`engine_holder.py`（线程安全单例 + 自检）、`/api/engine/selftest` 接口与“关于与部署”页“模型引擎自检”按钮；`scripts/regress_engine.py` 离线回归；health 增加模型状态。详见下方 G 节。

---

## 📌 v0.3 M1 实现定稿补丁（2026-11-23，优先级高于下文冲突描述）

### A. 端口与容器（实测定稿）

- **MySQL**：容器 `smoke-mysql`（实测镜像 **mysql:8.0.46**）、compose 项目 `smoke-detection`、命名卷 `smoke_mysql_data`、网络 `smoke-detection_default`，端口 `127.0.0.1:3307 -> 容器 3306`。用户已确认**不会同时启动多个项目的 compose**；注意现有 `trade-mysql` 也配置了宿主 3307，二者**禁止同时运行**：若要启动 trade-mysql，先 `docker stop smoke-mysql`，或改 `deploy/mysql/.env` 的 `SMOKE_MYSQL_HOST_PORT` 后重新 `up -d`。
- **Web**：`http://127.0.0.1:8010`。**8000 被本机 C-Lodop 云打印服务 `CLodopPrint32.exe`（PID 22852，Windows 原生常驻进程，非 Docker）占用，故避让到 8010**；若退出 C-Lodop，可在 `.env` 设 `WEB_PORT=8000` 后重启。
- **单一环境变量文件**：`deploy/mysql/.env`（`docker compose --env-file` 与 `run_web.py` 的 `load_dotenv` 共用同一份）；`deploy/mysql/.env.example` 为可提交模板；真实 `.env` 已加入 `.gitignore`。

### B. 视频源 Q7 定稿（任意本机路径）

- `SMOKE_LOCAL_PATH_ROOTS=*`：出厂默认**允许后端 Flask/OpenCV 进程读取当前 Windows 用户有权限的任意盘符/目录下视频与图片绝对路径**（浏览器只把路径字符串发给本机后端，文件读取不经过浏览器沙箱）。
- 保留底线：服务仅绑定 `127.0.0.1`；视频/图片扩展名白名单；路径接口只用于打开检测，**不提供任意文件浏览/下载**；将来若开放局域网或多人访问，必须把 `SMOKE_LOCAL_PATH_ROOTS` 收紧为分号 `;` 分隔的根目录并增加登录鉴权。
- 待确认：**单张图片检测是否提前到 P0**（当前 P0 实时管线面向视频文件/摄像头；多图与文件夹批量检测仍列 P1）。

### C. 参数生效时机（用户最终决定，覆盖 v0.2 的“三级热更”设计）

- **先在控制面板设好全部会话参数，再点“开始”；会话运行中参数面板整体锁定为只读，P0 不实现 `PATCH /api/session/params` 热更接口。**
- `conf / iou / imgsz / 投票窗口 / 投票阈值 / 事件冷却 / 心跳 / 快照 / 循环` 等参数随 `POST /api/session/start` 一次性传入，在该会话生命周期内固定；`GET /api/session/status` 回显当前生效值。要改参数：先停止会话 → 面板解锁修改 → 重新开始；切换视频源同样走“停止 → 以新源 start”（同一模型不重载）。
- 仅切换 `.pt` 模型权重需要重新 `YOLO(weight)` 加载（列 P1，会话停止后切换，并联动建议 imgsz）。

### D. M1 已交付并实测通过（2026-11-23 22:04）

- 新增文件：`run_web.py`、`requirements-web.txt`（锁定 **Flask 3.1.3 / Flask-SQLAlchemy 3.1.1 / SQLAlchemy 2.0.58 / PyMySQL 1.2.4 / cryptography 50.0.2 / python-dotenv 1.2.4**）、`deploy/mysql/docker-compose.yml`、`deploy/mysql/.env`、`deploy/mysql/.env.example`；`webapp/` 包（`__init__.py` 应用工厂、`config.py`、`extensions.py`、`models.py` 的 `DetectionEvent`、`blueprints/pages.py` 提供首页与 `/api/health`、`templates/index.html`、`static/css/app.css`、`static/js/app.js`）；`data/web_events/.gitkeep`、`data/web_uploads/.gitkeep`；`.gitignore` 增补 Web 运行产物与 `.env` 规则。
- 验证结果：`smoke-mysql` 容器 `healthy`，`smoke` 账号可登录，`smoke_detection` 库与 `detection_event` 表（18 列；索引 `idx_event_time`、`idx_source_time(source_id,event_time)`、`idx_status`）由 `db.create_all()` 自动建成；`GET /api/health` 返回 200 且 `code=0、db_ok=true、db_driver=mysql、version=0.1.0-m1`；`GET /` 返回 200（5169B，中文标题匹配）；Flask 运行日志无 traceback（开发服务器 WARNING 为预期，课设本机单用户使用）。
- 日常启动：容器已设 `restart: unless-stopped`（Docker Desktop 启动后通常自动拉起，也可 `docker start smoke-mysql`）；Web 验证进程已停止以释放 8010，用户在工程根 dl-gpu 终端执行 `python run_web.py` 后访问 <http://127.0.0.1:8010>。

### E. 仍待确认（不阻塞 M2 准备）

- **Q1** 投票默认值先按磁盘现状 **4/2**，M2 抽公共管线时核对 CLI 历史口径（曾用 5/3），台账/文档不写错；
- **Q2** Web 默认样例暂取横屏 `data/test_videos/smoke_test2.mp4`（两个视频都进下拉），M3 演示彩排最终确定；
- **Q5** P1 取舍、3–5 人分工、第 15–16 周答辩倒排；
- **Q6** 是否同意 M2 对 `scripts/infer_det_single.py` 做“抽 `utils/det_pipeline.py` 公共管线、CLI 行为不变”的薄重构（改前备份到 `runs/detect/audit/script_backup/` 并同视频回归）；
- **Q8（新）** 是否把“单张图片检测（本机路径/上传 1 张图 → 标注图展示，可选存事件）”从 P1 提前到 P0。

### F. v0.4 工程独立迁移（2026-11-23 深夜已执行并验证，方案 C）

**F.1 新工程根与边界**

- **Web 工程根（唯一运行/开发目录）**：`C:\Users\YS\Desktop\Study\AI_Train\smoke-monitor-web\`，与训练基地 `C:\Users\YS\Desktop\Study\AI_Train\smoke_detection\` 平级。
- 训练基地恢复为纯离线训练目录：仅保留 `scripts/ utils/ weights/ data/（数据集、test_videos、frames_to_label、smoke_cls_crop） runs/ docs/（训练件）` 与训练版 `.gitignore / requirements.txt / README.md`；M1 误放在训练根的 `webapp/ deploy/ run_web.py requirements-web.txt data/web_events data/web_uploads docs/Web监控系统设计方案.md` 已在“复制到新根 → MD5/清单核对 → 新根验证通过 → 压缩备份”后从旧位置精确删除，训练数据/脚本/权重/runs 均未改动。

**F.2 新工程结构与自包含制品（约 21.4MB）**

```text
smoke-monitor-web\
├─ run_web.py                 # 原样迁移，零改动（按自身目录定位 webapp/ 与 deploy/mysql/.env）
├─ requirements-web.txt
├─ .gitignore                 # v0.4 新建 Web 版（忽略 .env/instance/运行产物/_migration_backup）
├─ .vscode\settings.json      # 复制（仅 conda 环境管理器偏好）
├─ deploy\mysql\              # docker-compose.yml + .env + .env.example 整体迁移
├─ webapp\                    # Flask 包；仅 config.py 默认路径/版本随迁移调整
├─ docs\Web监控系统设计方案.md  # 本文档（唯一最新版，旧根副本已删）
├─ models\                    # 自包含检测权重（3 个，约 17.9MB）
│  ├─ smoke_cig_det_clean_best.pt        (5.945MB，clean 自训 30 轮，当前 DEFAULT)
│  ├─ smoke_cig_clean_n640_e150_best.pt (5.959MB，云端 n640/e150 回传)
│  └─ smoke_cig_clean_n960_e100_best.pt  (5.999MB，云端 n960/e100 回传)
├─ samples\                   # 自包含样例视频：smoke_test.mp4(2.245MB)、smoke_test2.mp4(1.115MB)
├─ data\web_events\ .gitkeep  # M4 违规快照运行目录
├─ data\web_uploads\ .gitkeep # M3 上传运行目录
└─ _migration_backup\         # 删旧前 M1 代码/配置 zip 快照（57.8KB），稳定后可手动删
```

> 分类权重 `smoke_cls_final.pt / yolov8s-cls.pt`、人脸 `yolov8n-face.pt`、COCO `yolov8n.pt` 属已搁置/实验路线，仍留训练基地 `weights/`，不进入 Web 自包含包；以后需要再复制。

**F.3 配置与部署变更**

- `webapp/config.py`：`PROJ_ROOT = Path(__file__).resolve().parent.parent` 在新层级下仍解析为 **Web 工程根**（代码结构未变，仅更新注释）；`DEFAULT_WEIGHTS` 默认改为 `<root>/models/smoke_cig_det_clean_best.pt`；`SAMPLE_VIDEO_DIR` 默认改为 `<root>/samples` 并新增 `SMOKE_SAMPLE_VIDEO_DIR` 环境变量覆盖（权重覆盖 `SMOKE_DEFAULT_WEIGHTS` 在 M1 已支持）；应用版本 `VERSION="0.1.1-m1.5"`。
- 真实 `deploy/mysql/.env` 内容与目录位置无关（仅 MySQL 连接 / WEB 端口 / `SMOKE_LOCAL_PATH_ROOTS=*`），原样迁移、**未写入任何本机绝对路径**；`deploy/mysql/.env.example` 补充“可选外部 models/samples 覆盖”模板。
- **Docker 管理目录改为新工程根**（compose 文件内仅命名卷、无 bind mount/build context）：

```powershell
cd C:\Users\YS\Desktop\Study\AI_Train\smoke-monitor-web
& "C:\Program Files\Docker\Docker\resources\bin\docker.exe" compose -f deploy/mysql/docker-compose.yml --env-file deploy/mysql/.env up -d
# 停止：... stop；看日志：... logs -f smoke-mysql
```

**F.4 迁移实测结果（2026-11-23 22:53–22:55）**

- 在新根首次 `compose up -d` 时，Compose 因工作目录/配置标签变化 **Recreated** 容器（预期内）；命名卷 `smoke_mysql_data` 保留，容器 **5 秒内恢复 healthy**，端口仍为 `127.0.0.1:3307->3306`；重建后 `SHOW TABLES` 仍有 `detection_event`、`SELECT COUNT(*)=0`，库表与卷数据无损。
- 新根 `python run_web.py` 监听 8010：`GET /api/health` 返回 200 `code=0、db_ok=true、db_driver=mysql、version=0.1.1-m1.5、model_loaded=false`；`GET /` 200（中文标题匹配），`/static/js/app.js`（3098B）、`/static/css/app.css`（4721B）均 200；`webapp.config` 解析的 `WEIGHTS`、`SAMPLES` 绝对路径均 `exists=True`。验证后测试 Flask 已停止、8010 确认释放（TaskStop 后曾出现子进程残留，本次已用端口核查兜底；M3 起服务验证后同样按端口查残留进程）。
- 删旧前备份：`_migration_backup/web_m1_pre_delete_20261123_225534.zip`（57.8KB，仅代码/配置/文档与占位；权重和视频未删源，故未打入）。

**F.5 新的日常启动 / 答辩启动方式**

```powershell
cd C:\Users\YS\Desktop\Study\AI_Train\smoke-monitor-web
conda activate dl-gpu
python run_web.py
```

浏览器访问 <http://127.0.0.1:8010>；MySQL 容器、账号、库表、3307/8010 端口与浏览器地址相较 M1 均无变化。若 `conda activate` 不可用，直接用 `C:\Users\YS\miniconda3\envs\dl-gpu\python.exe run_web.py`。

**F.6 M2 路线随方案 C 调整**

- Web **不再 import 训练基地 `utils/`**；M2 在新工程 `webapp/services/` 内，以训练基地 `scripts/infer_det_single.py`（动手前重新 Read，用户可能手改）已验证逻辑为蓝本，固化**在线推理引擎**（模型加载、投票状态、检测+绘制、JPEG 编码），保证 Web 工程可独立拷贝 / 运行 / 打入期末 zip；Web 内只维护这一份在线推理实现。
- 原 Q6“是否另对训练 CLI 抽 `utils/det_pipeline.py` 薄重构（改前备份 + 回归）”**降级为可选项**，不再阻塞 Web 的 M2/M3。
- 模型迭代后：把新 `best.pt` 复制进新工程 `models/`，或在 `deploy/mysql/.env` 设 `SMOKE_DEFAULT_WEIGHTS` 指向训练基地权重（免复制，仅本机开发期）。

**F.7 M3 前仍需用户拍板（迁移本身不阻塞）**

1. **Web 默认权重**：`models/` 三个检测权重当前默认仍是 clean 30 轮 `smoke_cig_det_clean_best.pt`；云端 n960/e100 复评指标略优但统一复评 #8 未做。建议 M2/M3 接模型时用同一视频 / valid 快速对比后再改 `DEFAULT_WEIGHTS` 或 `.env`。
2. **Q8** 单张图片检测是否从 P1 提前到 P0；**Q5** 组员分工与第 15–16 周答辩倒排；Q1 投票 4/2 vs 历史 5/3 在 M2 对照 CLI 定稿；Q2 默认样例 M3 彩排定（两个样例已在 `samples/`）。

---

## 0. 评审结论速览

### 0.1 已确认决策（2026-11-23）

1. **系统形态**：B/S 监控系统，浏览器前端 + Python Flask 后端 + YOLO 推理，三层齐全；职责前后端分离（HTTP/JSON + MJPEG），部署为本机单进程，`python run_web.py` 一键启动。
2. **前端技术**：**HTML + 原生 JavaScript + 原生 CSS，不使用 Node/npm 构建链**；第三方前端资源（若有）一律下载到 `webapp/static/vendor/` 本地化，**禁止公网 CDN**（答辩教室可能断网）。本机 Node v22/Vue 环境仅作为以后升级独立前端工程的备用条件。
3. **后端技术**：**Flask 3.1.3（dl-gpu 已安装）**；数据访问使用 **Flask-SQLAlchemy ORM**；实时画面 P0 用 MJPEG + 低频状态轮询，已安装的 Flask-SocketIO 5.7.0 暂不启用（列为 P1 可选）。
4. **数据库**：**MySQL 8.0 专用 Docker 容器为唯一主库**，容器名 `smoke-mysql`、宿主仅绑定 `127.0.0.1:3307`、独立数据卷 `smoke_mysql_data`、库 `smoke_detection`、专用账号 `smoke`；**不与**现有 `aitutor-mysql`、`trade-mysql`、`mysql8` 三个容器混用，不使用本机原生 `MySQL80` Windows 服务（保持停止/手动），MySQL Workbench 仅作客户端连接 `127.0.0.1:3307`。功能/性能上 MySQL 与 SQLite 对本项目差异很小，差异主要在部署形态；按用户决定**主路径只维护 MySQL**，仅保留 `SMOKE_DATABASE_URL` 可覆盖的手动 SQLite 应急逃生门（见 2.4），不做自动降级/双库测试。
5. **事件级违规记录**：**仅在多帧投票确认 ALARM 后触发记录**（不记录单帧原始检测）；同一视频源两次记录间隔不低于冷却时间，**默认 10s、前端可配（5–300s，后端校验）**；一次报警持续期间到点可“心跳”补记（开关默认开、可关）；按 `source_id` 独立计时（本期单源，兼容以后多路）。
6. **P0 基础范围已认可**：实时监控（视频输入、MJPEG、参数调节、投票状态、ALARM 快照）、违规记录页、CSV 导出；语音播报、模型切换、**多文件批量检测**、统计图表列入 P1。**v0.2 调整**：按用户第二轮反馈，把“**单个视频上传 + 本机路径引入**”从 P1 **提前进 P0**（见第 5.1、6.2 节）。
7. **答辩机器**：使用本人笔记本（16GB 内存、RTX4060 Laptop 8GB、Docker Desktop 29.8.2 / Compose v5.6.0、本地已有 `mysql:8.0` 镜像 1.1GB）；仍准备纯录屏兜底。
8. **AutoDL 云实例不进入演示链路**：仅用于离线训练；云权重已回传 `weights/`（`smoke_cig_clean_n640_e150_best.pt` 5.96MB、`smoke_cig_clean_n960_e100_best.pt` 6.00MB，大小正常），由本机 Flask 加载。
9. **视频源与调参方式（v0.2 新增，用户评审意见定稿方向）**：监控页视频源通过“**样例下拉 / 本机路径直读 / 浏览器上传 / 摄像头**”四种方式获得；**推理参数在前端面板可调**，后端做范围校验并按“即时生效 / 线程内安全应用 / 换模型需重载”三级处理（见 5.1.3、第 9 节）。

### 0.2 待用户最终确认（不阻塞 M1 的项已标注）

| 编号 | 待确认点 | 草案默认（未反对即按此实施） | 是否阻塞 M1 |
|---|---|---|---|
| Q1 | 投票参数：磁盘最新 `scripts/infer_det_single.py` 为 `VOTE_WINDOW=4 / VOTE_THRESHOLD=2`，与早前讨论的 5/3 不一致（疑似后续手改） | Web 默认先对齐磁盘 **4/2**，且页面可随时热调；**CLI 历史口径在 M2 抽公共管线时再核对**，台账/文档不写错 | 否（M2 前确认即可） |
| Q2 | 监控页默认样例源：CLI 现指 `smoke_test.mp4`（竖屏 2.25MB），近期出片多用 `smoke_test2.mp4`（横屏 1.12MB） | Web 配置独立默认 **`data/test_videos/smoke_test2.mp4`**，下拉同时提供两个；不改 CLI 常量；M3 彩排时可最终定 | 否（M3 前定即可） |
| Q3 | 新增目录布局 `webapp/`、`deploy/mysql/`、根目录 `run_web.py`（v0.2 另增 `services/source_resolver.py`、`blueprints/sources.py`，见第 4 节） | 按草案实施 | **是**（M1 落盘前若无异议即通过） |
| Q4 | MySQL 本地课设密码：`.env.example` 预置 `root/root123456`、`smoke/smoke123456`（仅绑定 127.0.0.1） | 按此实施，用户可自行修改 `.env`（真实密码无需发对话） | **是**（M1 起容器前） |
| Q5 | P1 取舍与 3–5 人分工（前端/后端/算法/文档）、第 15–16 周答辩倒排 | M1–M5 计划见第 11 节，评审时补充人员与日期 | 否（M5 前明确即可） |
| Q6 | 是否同意对 `scripts/infer_det_single.py` 做“抽公共管线”的薄重构（行为保持不变，改前备份+回归） | 同意后在 M2 执行；若不同意则 Web 侧新建引擎，但仍保持单一推理实现来源，避免两套逻辑漂移 | 否（M2 前确认） |
| Q7（v0.2 新增） | 本机路径直读的允许范围：默认允许工程根 + 当前用户 `Desktop/Downloads/Videos`，可在 `.env` 用 `LOCAL_PATH_ALLOWED_ROOTS` 追加目录，或设 `*` 允许本机任意视频（服务仅绑 127.0.0.1） | 采用默认白名单根；越界路径提示改用“上传” | 否（M3 前可纠正） |

---

## 1. 作业符合性、目标与非目标

### 1.1 作业要求映射

| 期末要求 | 本系统对应设计 |
|---|---|
| 可运行完整应用：前端展示 + 后端服务 + AI 模型推理 | 浏览器页面（前端）+ Flask（后端服务/API/会话调度）+ ultralytics YOLO（进程内推理） |
| 前后端分离（非强制，加分） | 前端为独立静态 HTML/JS/CSS，后端只提供 JSON API、MJPEG 流与静态文件，通信契约见第 6 节；部署同进程托管仅为降低现场风险，职责仍分离 |
| 前端可用 Web、后端推荐 Flask 等 | 原生 JS Web + **Flask 3.1.3**（作业点名框架） |
| 功能覆盖数据输入、AI 推理结果展示、业务逻辑处理 | **样例视频 / 本机路径 / 浏览器上传 / 摄像头**输入（P0），P1 多文件批量；实时画面、框、FPS、投票/报警展示；报警冷却、事件留证、记录管理、CSV 导出等业务闭环 |
| AI 部分：数据、标注、训练、优化、评估、部署 | 训练侧已有 clean 数据集、seed42 训练、云消融与评估台账（#8 待收尾）；本项目负责“模型部署：嵌入系统在线/离线推理”，模型页 P1 展示指标 |
| 提交：源码、依赖说明、环境配置文档、模型与数据集、系统文档（需求/设计/手册） | 本设计文档 + M5 产出《部署运行文档》《操作手册》、锁定 `requirements-web.txt`、`.env.example`、`schema.sql`、提交打包清单 |
| 答辩 3 分钟系统演示、现场环境稳定 | 本机部署、全离线前端依赖、MySQL 容器一键起、样例视频主线、录屏兜底（第 12 节） |

### 1.2 建设目标（本期）

1. 一条命令在本人笔记本启动完整监控系统，浏览器完成“选源（样例/路径/上传/摄像头）→ 调参 → 实时检测 → 投票报警 → 自动留证 → 违规记录查询/导出”闭环。
2. 推理链路与现行 `infer_det_single.py` 保持同一套检测/投票/绘制逻辑，不因为上 Web 而改变模型行为。
3. 工程结构清晰、依赖可复现、文档可支撑作业提交与答辩讲解（架构图、ER 说明、接口清单、部署手册）。
4. 为第②③步（特写 W_roi、空间分区融合 #10/#11）预留引擎扩展点，但**不提前实现未训练模型的空壳按钮或假数据**。

### 1.3 非目标（本期不做，写入设计文档“可扩展性”章节即可）

- 公网部署、HTTPS、域名、多用户与细粒度权限（本期本地单机单用户，仅绑定 `127.0.0.1`；登录鉴权列 P2）。
- WebRTC 低延迟、多路摄像头并发调度、分布式推理（P2）。
- Electron/Tauri 桌面壳、浏览器原生文件绝对路径回传（标准浏览器沙箱不允许，见 5.1.2；本期用“路径粘贴 + 文件上传”覆盖）。
- W_full + W_roi 双权重空间分区融合、人脸 crop 二阶段（待 #11 权重完成后按同一引擎接口插入）。
- 自动训练/在线微调（训练仍走 `scripts/det_train/` 与 AutoDL 离线流程）。
- 不引入 Node 构建链、不引入 Django/Spring Boot、不引入 Redis/MQ 等额外中间件（课设单机事件量不需要）。

---

## 2. 总体架构

### 2.1 架构图（可直接重绘进 PPT）

```
┌──────────────────────────── 浏览器（127.0.0.1:8000）────────────────────────────┐
│  实时监控页        违规记录页        批量检测(P1)   模型与统计(P1)   关于/部署      │
│  原生 HTML/CSS/JS（static/vendor 本地化，无 CDN）                                │
└───────────────┬───────────────────────────────────────┬──────────────────────┘
                │ HTTP/JSON（控制/事件/CRUD/上传，/api/*） │ MJPEG /api/stream.mjpeg（画面）
                ▼                                         │ 状态低频轮询 GET /api/session/status
┌──────────────────────────── Flask 进程（run_web.py，dl-gpu Python3.10）──────────┐
│ blueprints/pages · sources(源解析/上传) · session_stream · events · models(P1) · batch(P1) │
│ ────────────────────────────────────────────────────────────────────────────── │
│ services/session_manager（单例会话 + 后台抓帧/推理线程 + 最新帧缓存 + MJPEG 订阅） │
│ services/inference_pipeline（模型单例、逐帧检测、投票 deque、HUD/ALARM 绘制）      │
│ services/source_resolver（样例/本机路径/上传/摄像头：白名单根、扩展名校验、落盘）  │
│ services/event_recorder（ALARM 边沿 + 10s 冷却状态机 + 心跳 + 快照写盘）           │
│ services/event_repository（ORM CRUD/筛选/分页/CSV）  services/model_registry      │
│ webapp/models.py（DetectionEvent ORM）  config.py（集中配置/.env）  extensions(db) │
└───────────┬───────────────────────────────┬─────────────────────────────────────┘
            │ PyMySQL（127.0.0.1:3307）       │ OpenCV VideoCapture（全帧、不跳帧）
            ▼                                ▼
┌──────────────────────────┐      ┌──────────────────────────────────────────┐
│ Docker 容器 smoke-mysql   │      │ 视频源(P0)：data/test_videos 样例 /        │
│ mysql:8.0（本地镜像）      │      │ 本机白名单路径直读 / data/web_uploads 上传 /│
│ 卷 smoke_mysql_data        │      │ 摄像头 0；RTSP(P2)、多文件批量 data/batch_  │
│ 库 smoke_detection utf8mb4 │      │ input(P1)                                 │
│ 仅绑定 127.0.0.1:3307      │      └──────────────────────────────────────────┘
└──────────────────────────┘      ┌──────────────────────────────────────────┐
                                   │ 文件系统：weights/*.pt（3 个香烟权重）      │
                                   │ data/web_events/YYYY-MM-DD/*.jpg（快照）  │
                                   │ data/web_uploads/YYYY-MM-DD/*（上传,P0）   │
                                   │ instance/（应急 SQLite）                   │
                                   └──────────────────────────────────────────┘
   离线训练：AutoDL RTX4090D（不进入演示链路）→ best.pt 回传 weights/
```

### 2.2 进程与部署视图（答辩机）

- **进程 A：Docker Desktop + 容器 `smoke-mysql`**：开机后可手动 `docker start smoke-mysql` 或由 `unless-stopped` 策略随 Docker 启动；数据持久化在 named volume，删容器不丢数据。
- **进程 B：`python run_web.py`（dl-gpu）**：Flask 开发服务器 `threaded=True, debug=False, use_reloader=False`（**禁止 reloader**，避免双进程重复加载模型），仅监听 `127.0.0.1:8000`；推理在独立 daemon 线程，不阻塞 HTTP 工作线程。
- **客户端：本机浏览器**（Edge/Chrome）访问 `http://127.0.0.1:8000`；演示投影用浏览器全屏（F11）。浏览器与 Flask 在同一台笔记本，因此“本机路径直读”由后端进程完成，浏览器只负责把路径字符串发给后端。
- 课设定位为**本机单用户系统**，Flask 内置服务器足够；不按公网生产标准设计（文档明确说明，避免答辩被追问并发时夸大）。

### 2.3 关键技术决策记录（ADR 摘要，可进报告）

| 决策 | 选择 | 否决方案与理由 |
|---|---|---|
| 前端形态 | 原生 JS + 静态托管 | 桌面 PyQt：三层中“后端服务”弱、UI/打包/协作成本高、分离加分难体现；独立 Vue 工程：需 Node 构建链，本期增加环境复杂度（本机虽有 node，但 dl-gpu 运行时不需要）；移动端：教室网络与同网部署风险高 |
| 后端框架 | Flask 3.1.3 | Django：视频流/后台推理场景偏重；Spring Boot：引入 JVM+Python 双运行时与跨进程调用，答辩链路长（组员 Java 经验通过 Flask 路由/ORM 迁移即可）；FastAPI：性能与异步更好，但组员零 Python Web 经验时 Flask 心智最简单且作业点名 |
| 数据库 | Docker MySQL 8.0 主库 + Flask-SQLAlchemy | 直接用原生 sqlite3 硬编码：以后迁移要改驱动/SQL；混用现有项目 MySQL 容器：生命周期/端口/配置/账号耦合，答辩易被其他项目连累；纯 SQLite 主库：用户已熟悉 MySQL 且本机/Docker 条件现成，MySQL 更利于作业讲解与完整后端形态 |
| 视频源获取（v0.2） | 样例下拉 + 本机路径直读 + 浏览器上传 + 摄像头（均 P0） | 只做样例下拉：演示自己的视频不便；只做上传：本机大文件要重复拷贝一份；让网页直接回传文件绝对路径：标准浏览器沙箱禁止（`C:\fakepath`，见 5.1.2）；为此引入 Electron 桌面壳：超出期末 Web 系统范围与工时 |
| 推理调参（v0.2） | 前端面板全量可调，按“即时 / 线程内应用 / 换模型重载”三级生效，后端校验回显 | 参数全部写死后端常量：演示调参要重启；笼统宣称“全部热更”：投票窗口重建、imgsz 张量变化、模型权重重载均有状态/性能约束，需如实区分 |
| 实时画面 | 后端画框 + MJPEG over HTTP | WebRTC：信令/编码复杂，3 分钟演示不需要低延迟；前端 canvas 画框 + WS 坐标：前后端协议与渲染工作量更大，P0 无必要 |
| 实时状态 | 1s 低频 JSON 轮询 | P0 不启用 SocketIO，降低 eventlet/长连接与模型线程交互复杂度；P1 需要服务端主动推送报警时再启用已安装的 Flask-SocketIO |
| 图片存储 | 快照 JPG 存磁盘、DB 存相对路径 | 图片入 MySQL BLOB：表膨胀、备份/页面读取不便 |
| 模型运行位置 | 本机 Flask 进程内加载 | 演示时调用 AutoDL：云实例计费/释放/教室公网不可控 |

### 2.4 MySQL 与 SQLite 在本项目的真实差异（回应 Q：区别大吗）

- **功能与性能层面：差异很小**。本期只有事件表的增删查改、分页、筛选、CSV 导出，写入峰值受 10s 冷却限制（单源约 6 条/分钟、数百条/小时，每条元数据不足 1KB），SQLite 与 MySQL 都远未到瓶颈；通用 ORM 模型下业务代码无差异。
- **部署运维层面：差异明显**。MySQL 是独立服务（容器、端口、账号、密码、数据卷、字符集、启动顺序），SQLite 是 Python 内置驱动读写的单个文件（零外部依赖、随项目目录复制）。
- **最终策略（按用户决定）**：**主路径与文档只维护 MySQL 8.0 + Docker Compose**；代码通过 `SMOKE_DATABASE_URL` 环境变量配置连接串、ORM 不写 MySQL 专有列类型/SQL，因此保留一条**手动应急逃生门**：答辩前若容器确实无法恢复，可设置 `SMOKE_DATABASE_URL=sqlite:///<项目>/instance/smoke_emergency.db` 临时启动（表由 ORM 自动建）。**不做自动降级、不做双库自动化测试、不把 SQLite 写进主部署路径**；`/api/health` 与页脚显示当前驱动（mysql/sqlite），避免数据位置混淆。

---

## 3. （预留）

> 本节编号保留，正式版将“数据与 AI 模型说明”并入第 7、10 节与 M5 操作手册；评审时如需要可在此补充数据集来源、标注规范、训练指标摘要（待 #8 统一复评后回填，禁止凭终端片段写最终数值）。

---

## 4. 目录设计与代码复用边界

### 4.1 新增目录与文件（v0.2）

```
smoke_detection/
├─ run_web.py                         # 【新增】Web 一键启动：加载 .env、create_app、app.run(127.0.0.1:8000, threaded, debug=False)
├─ requirements-web.txt               # 【新增】Web 侧锁定版本（含已装 Flask 3.1.3 与新增 ORM/驱动/dotenv）
├─ deploy/
│  └─ mysql/
│     ├─ docker-compose.yml          # 【新增】smoke-mysql：127.0.0.1:3307->3306、独立卷、utf8mb4、buffer=128M、healthcheck
│     ├─ .env.example                # 【新增】root/app 密码样例；真实 .env 同目录且被 .gitignore
│     └─ initdb/01_schema.sql        # 【新增·可选】建库授权/表结构 SQL，主要供文档与老师查阅、手动部署
├─ webapp/
│  ├─ __init__.py                    # create_app()：配置、db.init_app、蓝图注册、启动连接检查与 db.create_all
│  ├─ config.py                      # 集中常量 + 环境变量（DB URL、默认权重/imgsz/conf/iou、投票、冷却、源白名单、目录、端口）
│  ├─ extensions.py                  # db = SQLAlchemy()（避免循环导入）
│  ├─ models.py                      # DetectionEvent ORM（通用列类型）
│  ├─ services/
│  │  ├─ model_registry.py           # 扫描 weights/*.pt、文件大小/修改时间、（P1）读取 results.csv 指标摘要、加载/切换
│  │  ├─ inference_pipeline.py        # 【或放 utils/det_pipeline.py】模型单例、process_frame、投票状态、绘制
│  │  ├─ session_manager.py          # 单例会话：抓帧线程、最新 JPEG+版本号、状态锁、启停 Event、MJPEG 订阅、参数应用
│  │  ├─ source_resolver.py          # 【v0.2】样例/本机路径/上传/摄像头解析：根白名单、扩展白名单、uuid 落盘、可选 probe
│  │  ├─ event_recorder.py           # 冷却状态机、快照写盘、调用 repository 入库
│  │  ├─ event_repository.py          # 事件筛选/分页/排序/CSV 行查询、删除
│  │  └─ media_store.py              # data/web_events/YYYY-MM-DD/<uuid>.jpg、send_from_directory 安全路径、删图联动
│  ├─ blueprints/
│  │  ├─ pages.py                    # 首页（单页标签骨架）
│  │  ├─ sources.py                  # 【v0.2】GET 样例列表、POST sources/resolve-local、POST sources/upload
│  │  ├─ session_stream.py           # start/stop/status/PATCH params + stream.mjpeg
│  │  ├─ events.py                   # 事件列表/详情/快照/标记/删除/导出 CSV
│  │  ├─ models_bp.py                # 【P1】权重列表/切换
│  │  └─ batch_jobs.py               # 【P1】多文件/目录批量检测任务与进度（单视频上传已在 sources.py，P0）
│  ├─ templates/index.html           # 单页五标签（P0 实现“实时监控/违规记录”，其余标签先放只读占位或隐藏）
│  └─ static/
│     ├─ css/app.css                 # 橙色主题 CSS 变量（借鉴参考图 #F07A1A 系）、响应式、投影字号
│     ├─ js/api.js                   # fetch 封装、统一信封/错误提示、查询串、上传进度与下载
│     ├─ js/monitor.js               # 源切换（样例/路径/上传/摄像头）、参数面板、启停、MJPEG、轮询、ALARM 横幅、（P1）语音
│     ├─ js/events.js                # 筛选、卡片墙、分页、大图 modal、标记/删除、CSV 下载
│     ├─ js/models.js                # 【P1】
│     ├─ js/batch.js                 # 【P1】
│     └─ vendor/                     # 第三方前端库本地化（P0 尽量零库）
├─ data/
│  ├─ web_events/                    # 【运行产物·P0】快照，按日期分目录（.gitignore；保留 .gitkeep 与 samples/ 少量样例）
│  ├─ web_uploads/                   # 【运行产物·P0】浏览器上传的视频，按日期分目录（.gitignore）
│  └─ batch_input/                   # 【P1】后端目录批量检测输入（.gitignore）
└─ instance/                         # 【应急】SQLite 文件目录（.gitignore）
```

> 设计原则遵循用户既有偏好：可复用离线/推理/存储逻辑放 `utils/` 或 `webapp/services/`，在线入口放 `scripts/` 与根目录 `run_web.py`；扁平清晰、中文注释、语义化命名，不做多余抽象层；Web 包内允许按蓝图/服务分文件，避免所有逻辑堆进一个 `app.py`。

### 4.2 现有代码复用与重构边界（M2，需 Q6 确认）

- `scripts/infer_det_single.py`（2026-11-23 重读，187 行）现行行为：
  - 默认权重 `weights/smoke_cig_det_clean_best.pt`、`FULL_IMGSZ=640`、`CONF_THRES=0.35`；
  - **当前投票常量 `VOTE_WINDOW=4 / VOTE_THRESHOLD=2`（Q1 待 M2 核对）**；
  - 每帧 `model.predict(frame, imgsz=640, conf=0.35, verbose=False)` 全帧推理；橙框 BGR `(0,165,255)`、英文 HUD、顶部黑条、红底 `SMOKING ALARM`；可选 `SAVE_VIDEO` 用 mp4v 写 `runs/detect_infer/`；`cv2.imshow + waitKey(q)`。
  - 旁证：`imgsz/conf` 本来就是每次 `predict` 的调用级参数，因此 Web 运行中改 `conf/iou/imgsz` 无需重新 `YOLO(weight)` 加载模型；只有换权重文件需要重建模型对象。
- 计划抽取单一推理实现到 `utils/det_pipeline.py`（推荐，符合“可复用逻辑进 utils”）：
  - `create_model(weight_path)`：加载 YOLO 单例；
  - `new_vote_state(window, threshold)` 与 `process_frame(model, frame, cfg, state) -> (annotated_bgr, result_dict)`，其中 `result_dict` 至少含 `n_boxes, boxes[{xyxy,conf}], vote_sum, vote_window, is_alarm, infer_ms, fps_ema, frame_idx`；
  - 绘制函数沿用现有橙框/英文 HUD/ALARM 样式（OpenCV 不支持中文，画面文字保持英文，中文信息放 Web 页面）。
  - `scripts/infer_det_single.py` 改为薄 CLI 入口：保留其顶部常量区与 `q` 退出、存片、结束统计，仅把“推理+投票+绘制”改为调用公共管线，**行为与默认值保持不变**；改前备份到 `runs/detect/audit/script_backup/`，并用同一视频回归对比帧数/报警/出片。
- `utils/stream.py`：`VideoStream` 的多源打开思路（文件/摄像头/HTTP/RTSP、数字字符串转摄像头 ID）可被会话管理器/source_resolver 参考或复用；**不使用**其 `run_inference_loop` 中的 `cv2.imshow/waitKey` 桌面循环与 `frame_interval` 跳帧（本项目全帧推理，Web 模式无窗口）。
- `utils/visualize.py`、`utils/eval_det_compare.py` 等本期不改动；`utils/eval_det_compare.py` 的 MODELS 配置与 #8 台账另行处理，不混入 Web 任务。
- 训练脚本、clean 数据集、标注目录本期一律不改。

### 4.3 `.gitignore` 增补（M1 随代码提交）

```gitignore
# Web 运行产物与密钥
.env
deploy/mysql/.env
instance/
data/web_events/*
!data/web_events/.gitkeep
!data/web_events/samples/
data/web_uploads/
data/batch_input/
```

（`runs/`、`*.log`、`__pycache__/` 等现有规则保留；模型与数据集大文件是否进 git 沿用现有规则，期末作业 zip 打包另按第 11 节清单处理，与 git 无关。）

---

## 5. 页面与交互设计

整体：顶部栏含系统名、当前权重、数据库驱动徽标（MySQL/SQLite）、视频源状态灯、当前时间；下方标签导航。主色借鉴参考图橙色（CSS 变量 `--brand:#F07A1A` 左右，实施时取色校准），视频区深色，投影分辨率下正文字号不小于 14px、关键状态 16px 以上。

### 5.1 Tab 1：实时监控（P0，v0.2 重写源与参数区）

#### 5.1.1 视频源区（四种来源，分段单选）

控制卡顶部用分段控件（Tab 风格单选）切换来源，选定后点“开始检测”；同一时刻仅一个会话。

1. **样例视频（`source_type=sample`，答辩主线，零操作）**
   - 下拉由 `GET /api/config/defaults`（或 `GET /api/sources/samples`）扫描 `data/test_videos/*.mp4` 等白名单扩展名得到，显示文件名与大小；默认选中 Q2 结论（草案 `smoke_test2.mp4`）。
2. **本机文件路径（`source_type=local`，零拷贝直读）**
   - 文本输入框 + “校验/读取信息”按钮：粘贴资源管理器地址栏或文件属性里的完整路径（如 `C:\Users\YS\Downloads\demo.mp4`），也支持相对工程根路径（如 `data/test_videos/smoke_test.mp4`）。
   - 调 `POST /api/sources/resolve-local`：后端 `Path.resolve()` 校验存在、是文件、扩展名白名单、在允许根内（Q7），可选 `probe=1` 用 OpenCV 试开并读取宽/高/fps/总帧数后立即释放；成功显示“可打开 · 1280×720 · 30fps · 12.4s”，失败显示中文原因（不存在 / 不在允许目录（可改用上传）/ 格式不支持 / 编码器无法打开）。
   - 安全：`start` 时后端**再次**解析校验，不信任前端上次结果；允许根默认工程根 + `~/Desktop`、`~/Downloads`、`~/Videos`，`.env` 可追加或设 `*`（仅因服务只绑回环地址，课设单机可接受；文档写明风险）。
3. **上传视频（`source_type=upload`，浏览器标准方式）**
   - 文件选择（`accept="video/*"`）+ 拖拽区，单文件；`POST /api/sources/upload` 用 `FormData` 上传并显示进度条（`api.js` 用 `XMLHttpRequest` 的 `upload.onprogress`，fetch 上传进度支持不一致）。
   - 后端流式保存到 `data/web_uploads/YYYY-MM-DD/<uuid4><ext>`（**不用原始文件名落盘**，防穿越/覆盖），白名单 `mp4/mov/avi/mkv/m4v/webm`，大小受 `MAX_CONTENT_LENGTH`（默认 500MB，`.env` 可调）限制；成功后前端自动把该上传记录选为待开始源（`source=stored_relpath`），并显示原始文件名/大小。
   - 上传文件保留在磁盘便于复用，M5 手册说明可定期手工清理；P2 再做自动清理。
4. **摄像头（`source_type=camera`）**
   - 设备号输入默认 `0`（Windows 若默认后端打不开，M3 实测可在后端用 `CAP_DSHOW` 尝试）；设备枚举下拉列 P1（探测会短暂占用摄像头，P0 不做自动枚举）。
   - RTSP/HTTP 网络流输入框在 P0 **显示但禁用**并标注“P2”，避免未测试能力进入答辩演示。

#### 5.1.2 关键浏览器限制说明（回应“上传文件（本地可路径引入）”）

- 标准浏览器里 `<input type="file">` 出于安全沙箱，**网页 JS 拿不到所选文件的真实绝对路径**，`input.value` 只会是 `C:\fakepath\文件名.mp4` 这类假路径；浏览器内的 `File` 对象也不能被独立运行的 Flask 进程直接读取，**必须把文件内容上传到后端**后才能由 `cv2.VideoCapture` 打开。
- 因此“像桌面程序一样点系统文件框、后端直接按原路径读盘”在纯浏览器方案里不成立（除非上 Electron/Tauri 桌面壳，本期不做）。本机部署下用 **“路径粘贴直读（适合知道路径的本机视频，零拷贝）+ 上传（适合任意位置/拖拽，拷贝到工程目录）”** 两个入口覆盖同一诉求；两者最终都由后端解析为本地绝对路径交给 OpenCV。

#### 5.1.3 推理参数面板（前端可调，三级生效）

| 前端控件 | 字段/默认 | 生效时机（后端如实实现与回显） |
|---|---|---|
| 置信度滑块 0.05–0.95（步进 .01） | `conf=0.35` | **下一帧立即生效**：每帧 `predict(conf=...)`；PATCH 热更，推理线程加锁读取 |
| NMS IoU 滑块 0.10–0.90 | `iou=0.70`（ultralytics 默认值，M3 实测确认） | **下一帧立即生效**：每帧 `predict(iou=...)` |
| 投票阈值数字/滑块 1–窗口值 | `vote_threshold`（Q1，草案 2） | **下一帧立即生效**（仅改判定阈值，不动 deque）；后端校验 `1≤threshold≤window`，越界返回 clamp 后值供前端回显 |
| 投票窗口数字 1–15 | `vote_window`（Q1，草案 4） | **推理线程内安全应用**：下一帧在拥有投票状态的线程里重建 `deque(maxlen=N)`，拷贝旧窗口最近 min(旧长,新长) 个投票，再同步校验阈值；不重新加载模型、不重启 Flask |
| 推理分辨率下拉 320/480/640/960 | `imgsz=640` | **推理线程内安全应用**：下一帧 `predict(imgsz=...)` 即用新值，权重不重载；切换后首帧可能因张量尺寸变化有短暂抖动，前端状态区显示“参数应用中”，无需停止会话（用户也可停止后再改，结果一致） |
| 事件冷却秒数 5–300 | `event_cooldown_sec=10` | **下一帧立即生效**（event_recorder 加锁读取，clamp 到 5–300） |
| 持续报警心跳开关 | `heartbeat=true` | 立即生效 |
| 保存事件快照开关 | `save_snapshot=true` | 立即生效（关闭后 ALARM 只更新状态不写库图，M4 实现） |
| 视频结束循环播放复选框 | `loop=false` | 立即生效（会话线程每帧检查；仅文件源） |
| 模型下拉（P1） | `model_name=smoke_cig_det_clean_best.pt` | **需重新加载模型**：P1 仅允许会话停止后切换；切换时 `YOLO(新权重)` 重建单例并联动建议 imgsz（n960 权重默认 960，可覆盖） |

- 所有参数既在 `POST /api/session/start` 的 body 中可带初始值，也可在运行中通过 `PATCH /api/session/params` 热更；**后端不信任前端，统一做类型转换、范围校验/clamp，并在响应 `data.applied` 返回最终生效值**，前端据此回显，避免滑块显示与实际运行值不一致。
- P0 参数仅作用于当前会话与页面（刷新页面回到 `/api/config/defaults`）；“保存为本机默认值”列 P1（写 `.env` 或 `instance/ui_settings.json`），P0 不做写配置文件逻辑。
- P1 控件：模型下拉（三个真实香烟权重，显示文件名与大小）、语音播报开关（5.4）。

#### 5.1.4 画面卡与状态卡

- **中栏 视频卡**
  - `<img id="stream" src="/api/stream.mjpeg">` 自适应宽度、保持源比例；未开始时显示深色占位与“请选择视频源并开始”。
  - ALARM 时画面右上角已有后端红色 `SMOKING ALARM`，前端同步显示红色横幅/卡片描边与最近报警时间（双保险，不开声音也清晰）。
  - 视频文件播放到结尾：未勾选循环时会话进入 `ended`，后端释放 capture、保留最后一帧或发结束占位帧，前端提示“播放结束，可重新开始”；勾选循环时后端重新打开同一文件循环播放（循环可能重复产生事件，由 10s 冷却限流，界面注明）。
- **右栏 状态卡（1s 轮询）**
  - 运行状态（idle/starting/running/ended/error）、当前来源（类型+展示名）、FPS（EMA）、最近一帧推理 ms、帧号/视频时间、当前香烟框数、投票 `sum/window`、当前 conf/iou/imgsz、会话内 ALARM 次数、最近事件时间、当前模型、DB 驱动。
  - 错误态用醒目中文条展示 `last_error`（如“视频无法打开/摄像头被占用/数据库不可写”）。
  - P1：本次会话/今日事件数、近 7 天事件柱状图（原生 canvas 或本地化图表库）、当前帧检测明细表（类别/conf/x1y1x2y2）。
- **交互时序**：选源/填参 → `POST /api/session/start` → 前端置 `<img>` 地址并开始轮询 `/api/session/status` → 后端启动会话线程与 MJPEG 生成器 → 运行中 PATCH 参数即时应用 → 停止/结束 → `POST /api/session/stop`（或检测到 ended）→ 前端清空流地址、恢复按钮。切换来源时前端自动执行“stop（若在运行）→ 以新源 start”，对用户表现为“应用并切换”。

### 5.2 Tab 2：违规记录（P0，对应“随时查看违规记录画面”）

- 筛选栏：日期范围、视频源、状态（全部/未处理/确认抽烟/误报）、每页条数（12/24/48）；按钮：查询、重置、**导出 CSV（utf-8-sig，Excel 直接打开不乱码）**、刷新。
- 卡片墙：快照缩略图（后端标注帧 JPG）、事件时间、源名称、最高 conf、投票 `sum/window`、状态徽标、模型名、记录原因（报警开始/心跳）；点击打开大图 Modal。
- 详情 Modal：大图、bbox 坐标列表、帧号/视频内时间（文件源）、墙钟时间、快照相对路径、备注；操作：标记“确认抽烟 / 误报”（可填备注）、删除（二次确认，后端删库并删快照文件）、下载原图。
- 底部分页：总数、页码、上一页/下一页、跳页；空态给出“暂无 ALARM 事件，请先在实时监控页运行样例视频或上传视频”。
- P1：按源清空（需输入确认）、事件前后 5s 短视频片段回放（环形帧缓冲）。

### 5.3 P1 标签页（本期预留，评审决定是否提前）

- **批量检测（P1，区别于 P0 的单视频上传）**：一次选择多个图片/视频文件上传，或扫描后端固定目录 `data/batch_input/` → 后台任务逐文件推理 → 进度条 → 结果表（文件名、类别、conf、坐标、标注图/视频下载、CSV/zip 导出），对应参考图“图片选择/文件夹选择/结果导出”。标准浏览器仍不能直接把本地文件夹绝对路径交给后端，故以“多文件上传（`webkitdirectory` 仅用于组织文件内容上传）”或“后端固定输入目录扫描”实现。
- **模型与统计**：`weights/` 权重列表（仅真实存在的 `.pt`，禁止假模型）、当前权重与默认 imgsz、（#8 完成后）展示 P/R/mAP 与训练曲线缩略图、事件统计图表、存储占用。
- **关于与部署**：项目背景、系统架构图、数据流、操作手册摘要、数据集与模型来源/合规说明、版本与当前 DB 驱动。

### 5.4 语音播报（P1，零额外依赖）

使用浏览器内置 `window.speechSynthesis` 中文播报“检测到抽烟行为”，前端开关默认关或开由评审定；复用事件冷却做语音节流（避免连续播报）；用户点击“开始”即满足浏览器音频解锁策略；**视觉 ALARM 始终为主，语音故障不影响主流程**。

---

## 6. API 契约（P0，v0.2 增补源接口）

### 6.1 通用约定

- 除 `GET /api/stream.mjpeg`（`multipart/x-mixed-replace`）与 `GET /api/events/export.csv`（文件下载）外，统一 JSON 信封：

```json
{ "code": 0, "msg": "ok", "data": { } }
```

  成功 `code=0`；业务错误 `code!=0` 且配合 4xx/5xx HTTP 状态，`msg` 为可展示中文。
- 时间字段统一 ISO8601 字符串（本地时区，`YYYY-MM-DD HH:MM:SS` 亦可，实施时固定一种并在文档说明）；分页参数 `page` 从 1 开始。
- 所有 `/api/*` 仅监听 `127.0.0.1`；快照/上传文件通过受控路由或 `send_from_directory` 提供，禁止拼接绝对路径造成目录穿越；`local` 源允许根校验仅用于 `cv2.VideoCapture` 读视频，不提供任意文件下载接口。

### 6.2 P0 端点清单（v0.2）

| 方法 | 路径 | 作用 | 关键请求/响应字段 |
|---|---|---|---|
| GET | `/api/health` | 健康检查、DB ping、驱动标识、模型加载状态、版本 | resp `db_driver`, `db_ok`, `model_loaded`, `version` |
| GET | `/api/config/defaults` | 前端初始配置与可选项 | `conf=0.35`, `iou=0.70`, `imgsz=640`, `vote_window`, `vote_threshold`, `event_cooldown_sec=10`, `heartbeat=true`, `save_snapshot=true`, `loop=false`, `samples[]`, `camera_default=0`, `allowed_source_roots[]`, `allowed_video_exts[]`, `upload_max_mb` |
| GET | `/api/sources/samples` | 扫描样例视频目录（也可并入 defaults，实施二选一，另一路径保留兼容或不实现） | resp `items[{name,size_bytes}]` |
| POST | `/api/sources/resolve-local` | 校验本机路径并可选试开取媒体信息（v0.2） | req `{path: string, probe?: bool}`；resp `{resolved_path, exists, is_file, ext, size_bytes, in_allowed_root, probe?:{width,height,fps,frame_count}}`；失败返回中文 `msg`（越界/不存在/扩展名/无法打开） |
| POST | `/api/sources/upload` | 上传单个视频，流式落盘到 `data/web_uploads/YYYY-MM-DD/<uuid><ext>`（v0.2） | req `multipart/form-data` 字段 `file`；resp `{upload_id, stored_relpath, original_name, size_bytes, ext}`；超限 413、扩展不支持 400 |
| POST | `/api/session/start` | 创建并启动唯一推理会话 | req `source_type`(**sample/local/upload/camera**), `source`（sample=文件名；local=绝对/相对路径；upload=stored_relpath；camera=设备号）, `conf?`, `iou?`, `imgsz?`, `vote_window?`, `vote_threshold?`, `loop?`, `event_cooldown_sec?`, `heartbeat?`, `save_snapshot?`；resp `session_id` 与归一化后的 `applied` |
| POST | `/api/session/stop` | 停止会话、释放 capture 与线程 | — |
| GET | `/api/session/status` | 轮询会话与最新推理状态 | `running,state(idle/starting/running/ended/error),source_type,source_display,frame_idx,video_time_sec,fps,infer_ms,n_boxes,vote_sum,vote_window,conf,iou,imgsz,alarm,alarm_count,last_event_at,model_name,last_error` |
| GET | `/api/stream.mjpeg` | MJPEG 画面流（无会话时返回占位 JPG 或 409，实施固定一种） | Header `Content-Type: multipart/x-mixed-replace; boundary=frame` |
| PATCH | `/api/session/params` | 运行时热更参数（见 5.1.3 分级） | req 任意可更字段：`conf,iou,vote_threshold,vote_window,imgsz,event_cooldown_sec,heartbeat,save_snapshot,loop`；resp `applied{...最终值}`、`requires_model_reload=false`（模型切换走 P1 接口）；非法值返回 clamp 后值或 400 中文提示 |
| GET | `/api/events` | 分页筛选事件 | query `page,size,date_from,date_to,source,status`；resp `total,page,size,items[]` |
| GET | `/api/events/<id>` | 事件详情（含解析后的 `boxes`） | — |
| GET | `/api/events/<id>/snapshot` | 事件快照图片（受控文件响应） | `image/jpeg` |
| POST | `/api/events/<id>/label` | 标记确认/误报与备注 | req `status`(confirmed/false_alarm/open), `note?` |
| DELETE | `/api/events/<id>` | 删除事件：先提交删 DB 行，再删快照文件（文件失败仅记日志，避免孤儿 DB 行；定期清理孤儿文件列 P2） | — |
| GET | `/api/events/export.csv` | 按当前筛选导出 CSV（utf-8-sig） | query 同列表；`Content-Disposition: attachment; filename=events_YYYYMMDD_HHMMSS.csv` |

### 6.3 会话状态示例（v0.2 增加源类型与实时参数）

```json
{
  "code": 0, "msg": "ok",
  "data": {
    "running": true, "state": "running", "source_type": "upload",
    "source_display": "demo_smoke.mp4",
    "frame_idx": 186, "video_time_sec": 6.2, "fps": 24.6, "infer_ms": 9.8,
    "n_boxes": 1, "vote_sum": 2, "vote_window": 4,
    "conf": 0.35, "iou": 0.70, "imgsz": 640,
    "alarm": true, "alarm_count": 3,
    "last_event_at": "2026-11-23 21:40:12",
    "model_name": "smoke_cig_det_clean_best.pt", "last_error": ""
  }
}
```

### 6.4 P1 端点（预留，不在 P0 实现空壳）

`GET /api/models`、`POST /api/session/model`（会话停止时切换并记录该权重默认 imgsz）、`POST /api/batch/jobs` + `GET /api/batch/jobs/<id>`（多文件/目录批量，区别于已提前的单视频 `/api/sources/upload`）、`GET /api/stats/summary?days=7`；若启用服务端推送再评估 Flask-SocketIO 事件名与房间。

---

## 7. 事件级记录设计（用户已确认口径）

### 7.1 触发与冷却状态机

- **触发源**：仅当帧级投票结果 `is_alarm=True` 才进入记录评估；`n_boxes>0 但未形成投票 ALARM` 的单帧/偶发检测只显示、不落库（调试用 `RECORD_TRIGGER=detection` 开关仅作后端隐藏配置，正式演示固定 `alarm`）。
- **每源状态**（`session_manager`/`event_recorder` 内存字典，key=`source_id`，本期单源）：
  - `last_saved_ts`：最近一次成功记录墙钟；
  - `alarm_active`：当前是否处于连续报警段；
  - `last_heartbeat_ts`：最近心跳记录时间。
- **转移规则**（`cooldown = event_cooldown_sec`，默认 10.0s，PATCH 可热更，后端 clamp 到 5–300s）：
  1. 收到 ALARM 且（无 `last_saved_ts` 或 `now-last_saved_ts ≥ cooldown`）：创建事件，`reason=alarm_start`，保存当前**已标注帧**快照，更新两个时间戳，`alarm_active=True`。
  2. ALARM 持续中且距上次记录不足 cooldown：跳过，不写库不写图。
  3. ALARM 持续中且到 cooldown、`heartbeat=true`：再记一条 `reason=heartbeat` 的持续证据；`heartbeat=false` 时同一段报警只保留首张。
  4. 连续非 ALARM 帧到达：置 `alarm_active=False`（P1 可加报警解除迟滞帧数，避免临界抖动反复起段；P0 用投票结果直接复位）。
  5. 任意同一 `source_id` 的两条事件墙钟差严格 ≥ cooldown；多源各自计时，互不饿死。
- 会话停止/视频结束/切换来源：清空该会话的内存冷却状态（历史事件与快照已持久化）；重新开始同一视频视为新会话，可再次记录（由冷却与手动删除控制重复，文档说明）。

### 7.2 事件表 `detection_event`（ORM 通用类型；MySQL DDL 由 `db.create_all()` 生成，另存 `initdb/01_schema.sql` 供查阅）

| 列 | 类型（ORM / MySQL） | 约束与说明 |
|---|---|---|
| `id` | Integer / INT AUTO_INCREMENT | 主键 |
| `event_time` | DateTime(timezone 无关，存本地时间) / DATETIME(6) | 非空，索引；报警记录墙钟 |
| `source_id` | String(64) / VARCHAR(64) | 源实例标识（本期可用 `sample:<文件名>`/`local:<hash>`/`upload:<id>`/`camera:0`） |
| `source_type` | String(16) / VARCHAR(16) | `sample`/`local`/`upload`/`camera`/`rtsp`(P2) |
| `source_name` | String(255) / VARCHAR(255) | 展示名（样例/上传原始文件名/摄像头0；local 可存文件名，不把敏感绝对路径作为页面主展示） |
| `frame_index` | Integer / INT NULL | 文件源帧号；实时流可空 |
| `video_time_sec` | Float / FLOAT NULL | 文件源 `frame_index/fps`；实时流空 |
| `max_conf` | Float / FLOAT | 该事件帧最高香烟置信度 |
| `vote_sum` | Integer / INT | 记录时投票票数 |
| `vote_window` | Integer / INT | 投票窗口长度 |
| `model_name` | String(128) / VARCHAR(128) | 产生事件的权重文件名（可追溯） |
| `snapshot_relpath` | String(512) / VARCHAR(512) | 相对 `data/web_events/` 的快照路径，DB 不存图片二进制 |
| `bbox_json` | Text / TEXT | 该帧烟框 `[{xyxy,conf}]` 的 JSON 字符串（通用 Text，避免 MySQL JSON 专有类型） |
| `status` | String(16) / VARCHAR(16) | 默认 `open`；`confirmed`/`false_alarm` |
| `reason` | String(16) / VARCHAR(16) | `alarm_start`/`heartbeat`（P0 保留列，便于讲解冷却行为） |
| `note` | String(255) / VARCHAR(255) NULL | 人工备注/误报原因 |
| `created_at` | DateTime / DATETIME(6) | 入库时间，默认当前时间 |

索引：`idx_event_time(event_time)`、`idx_source_time(source_id, event_time)`、`idx_status(status)`。本期仅一张表，不预设用户表/任务表（P1 确有批量任务持久化时再新增，避免空设计）。

### 7.3 快照与文件布局

- 目录：`data/web_events/YYYY-MM-DD/<uuid4>.jpg`（按事件日期分目录；用 uuid 文件名先写盘再入库，避免依赖自增 id 重命名）。
- 内容：与 MJPEG 推流同一帧的后端标注图（橙框、英文 HUD、`SMOKING ALARM` 横幅），`cv2.imencode('.jpg', frame, [IMWRITE_JPEG_QUALITY,90])` 后写文件。
- 删除：`DELETE /api/events/<id>` 先提交数据库删除，再尝试删除快照；文件缺失不回滚数据库。
- 备份：事件备份 = MySQL 逻辑导出（`mysqldump`）+ 整个 `data/web_events/` 目录（如需保留上传源视频，另备 `data/web_uploads/`）；M5 部署文档给 Windows/PowerShell 可用的备份命令（注意 PowerShell `>` 默认编码问题，优先 `docker exec ... mysqldump -r /tmp/x.sql` 后 `docker cp`，实施时验证后写文档，不凭印象给可能乱码的重定向命令）。

---

## 8. 数据库与 Docker MySQL 部署设计

### 8.1 `deploy/mysql/docker-compose.yml`（M1 落盘内容预览，镜像 tag 已核实本地存在）

```yaml
services:
  smoke-mysql:
    image: mysql:8.0                      # 本机 docker images 已有，无需拉取
    container_name: smoke-mysql
    restart: unless-stopped               # 若不希望随 Docker 自启可改 no，演示前 docker start smoke-mysql
    ports:
      - "127.0.0.1:3307:3306"             # 仅本机可连；左侧 3307 避开现有容器/原生服务常用的 3306
    environment:
      MYSQL_ROOT_PASSWORD: ${SMOKE_MYSQL_ROOT_PWD}
      MYSQL_DATABASE: smoke_detection
      MYSQL_USER: smoke
      MYSQL_PASSWORD: ${SMOKE_MYSQL_APP_PWD}
      TZ: Asia/Shanghai
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_0900_ai_ci
      - --innodb-buffer-pool-size=128M    # 16GB 笔记本、课设小负载，限制内存占用
    volumes:
      - smoke_mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-usmoke", "-p${SMOKE_MYSQL_APP_PWD}"]
      interval: 10s
      timeout: 5s
      retries: 10

volumes:
  smoke_mysql_data:
```

- 不加入 `student-digital-human_*`、`tomcat-net`、`docker_default` 等现有网络，使用 compose 默认独立网络；Flask 跑在宿主机，经 `127.0.0.1:3307` 映射端口连接。
- 现有 `aitutor-mysql`、`trade-mysql`、`mysql8` 保持停止、不修改、不启动其容器；若以后启动其他项目容器，注意它们各自端口（M1 用 `docker inspect HostConfig.PortBindings` 复核并在部署文档登记一张“本机容器端口表”；当前 `NetworkSettings.Ports` 在停止态为空属正常）。
- 本机原生 `MySQL80` Windows 服务保持 `Manual/Stopped`（`mysqld.exe` 路径 `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe`），避免占用 3306 与多实例数据目录混淆；MySQL Workbench 新建连接 `127.0.0.1:3307`，用户 `smoke` 或 `root`。

### 8.2 Flask 数据库配置（`webapp/config.py` + `.env`）

- 安装新增依赖：`Flask-SQLAlchemy`（3.1.x，兼容 Flask 3.1）、`PyMySQL`、`cryptography`（MySQL8 `caching_sha2_password` 连接需要）、`python-dotenv`；Flask 已在 dl-gpu 安装。
- `run_web.py` 启动时显式 `load_dotenv()` 加载工程根 `.env`（compose 用 `--env-file deploy/mysql/.env` 或在 compose 中 `env_file` 共用同一份密码；**M1 固定单一 `.env` 位置并在文档写清**，避免两处不一致）。
- 默认连接串（课设本地，仅绑回环地址）：

```text
SMOKE_DATABASE_URL=mysql+pymysql://smoke:smoke123456@127.0.0.1:3307/smoke_detection?charset=utf8mb4
```

- 启动流程：`db.init_app` → `SELECT 1` 连接检查 → `db.create_all()`（课设自动建表）；连接失败时打印中文排查清单（Docker Desktop 是否启动、`docker ps -a | findstr smoke-mysql`、容器健康状态、3307 端口、`.env` 密码），并提示应急连接串（见 2.4），**不静默切换数据库**。
- `/api/health` 与页脚徽标展示驱动名（由 URL scheme 解析：`mysql+pymysql`→MySQL，`sqlite`→SQLite）。

### 8.3 常用运维命令（M5 文档展开并实测）

- 启动/停止/查看日志：`docker compose -f deploy/mysql/docker-compose.yml up -d`、`... down`（**不加 `-v`**，加 `-v` 会删数据卷）、`docker logs smoke-mysql`。
- Workbench 连接：`127.0.0.1:3307`。
- 备份/恢复：M5 在本机实测 `mysqldump`（容器内 `-r` 落文件 + `docker cp` 到工程 `backups/`）与 `data/web_events/`（必要时 `data/web_uploads/`）一并复制；恢复步骤写入操作手册。

---

## 9. 推理会话、并发与性能设计

1. **单例会话**：P0 全局仅一个 `SessionManager` 会话；重复 `start` 返回 `409/业务错误`（前端先 stop 再 start），避免源/线程泄漏。
2. **线程模型**：
   - 推理 daemon 线程：`VideoCapture.read()` → 应用待生效参数（投票窗口重建等）→ `process_frame()`（含投票状态更新与绘制）→ 事件记录评估 → 编码最新 JPEG 写入带锁缓存（`latest_jpeg`、`version`、`status_dict`），用 `threading.Condition` 通知 MJPEG 生成器；
   - Flask 请求线程：`start/stop/status/PATCH/events/sources` 读写受锁保护的状态快照；MJPEG 生成器等待新 `version` 后 yield 最新帧，**多个浏览器标签共享同一次推理**，不随观看者重复加载模型/推理；
   - 停止：`threading.Event` 通知循环退出，`cap.release()`、唤醒所有 MJPEG 等待者、线程 `join(timeout)`，`run_web.py` 退出时 `finally` 兜底释放。
3. **参数生效分级（v0.2，对应 5.1.3）**：
   - **即时（加锁标量）**：`conf`、`iou`、`vote_threshold`、`event_cooldown_sec`、`heartbeat`、`save_snapshot`、`loop`，推理/记录线程下一帧读取；
   - **线程内应用（有状态）**：`vote_window` 由推理线程重建 `deque(maxlen=N)` 并保留最近投票；`imgsz` 在下一帧 `predict` 调用生效（模型不重载，首帧可能抖动）；
   - **换源**：stop 旧 capture → 重置帧号/投票/事件会话状态 → 打开新源（同一权重不重载），前端表现为“应用并切换”；
   - **换模型（P1）**：会话停止后由 `model_registry` 释放并重建 YOLO 单例，维护“权重文件名→建议 imgsz”映射（n 系 640、n960 权重 960），允许高级用户覆盖；运行中切换列 P1 可选项（在推理线程安全点重载），P0 不实现。
   - 所有 PATCH 经后端校验/clamp 并回传 `applied` 最终值。
4. **资源与异常**：摄像头被占用/视频不存在/流打开失败/上传编码不支持 → 会话进入 `error` 并把中文原因写入 `status.last_error`，线程干净退出、释放 capture；模型文件缺失在 `start` 前校验并提示；`resolve-local` 的 `probe` 与会话打开使用同一套扩展/打开逻辑，减少“校验能过、播放失败”的偏差。
5. **性能基线（实施 M3 实测回填，禁止提前写承诺数值）**：记录本机 RTX4060 上 n 权重、imgsz640、b1 视频流的平均推理 ms、端到端 FPS、内存/显存占用；若帧率不足，优先降 `imgsz`（480/320）而非跳帧，保证画框不闪烁（沿用用户“全帧推理、不跳帧”的要求）。上传大文件走本机回环，不把上传耗时计入推理性能。
6. **浏览器兼容**：以本机 Edge/Chrome 最新版为演示基准；MJPEG 用 `<img>` 原生支持，上传进度用 XHR；页面断开/刷新不强制停止后端会话（P0 由停止按钮管理），但 `run_web.py` 进程退出一定释放摄像头。

---

## 10. 依赖、配置与一键启动

### 10.1 `requirements-web.txt`（M1 安装后 `pip freeze` 锁定精确版本并提交）

```text
Flask==3.1.3            # dl-gpu 已装
Flask-SQLAlchemy        # M1 安装兼容 Flask3.1 的 3.1.x，随后 freeze
PyMySQL                 # MySQL 驱动
cryptography            # MySQL8 caching_sha2_password
python-dotenv           # run_web.py 显式加载 .env
# 以下已在 dl-gpu，列出用于环境文档与 freeze 核对，不在 Web 任务中升级：
ultralytics==8.0.200
opencv-python==4.10.0.84
```

- 安装命令（本机 PowerShell，必要时使用阿里云源）：
  `C:\Users\YS\miniconda3\envs\dl-gpu\python.exe -m pip install Flask-SQLAlchemy PyMySQL cryptography python-dotenv -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com`
- 风险记录：dl-gpu 同时存在 `opencv-python 4.10.0.84` 与 `opencv-contrib-python 5.0.0.93`（版本不一致的共存组合）。当前训练/推理可运行，**本期不主动卸载/升级**；若 M2/M3 出现 `import cv2`、`VideoCapture` 或编码异常，再在备份环境后统一为同一 OpenCV 主版本并记录到部署文档。
- Flask-SocketIO 5.7.0 已随环境存在，P0 不 `import`、不初始化，避免额外运行条件。

### 10.2 配置项清单（`webapp/config.py` 集中常量，环境变量优先；v0.2 增补源相关）

| 配置 | 默认值 | 说明 |
|---|---|---|
| `WEB_HOST` / `WEB_PORT` | `127.0.0.1` / `8000` | 仅本机监听；端口占用时改 `.env` |
| `SMOKE_DATABASE_URL` | 本机 MySQL 连接串（8.2） | 应急可覆盖为 sqlite（2.4） |
| `DEFAULT_WEIGHTS` | `weights/smoke_cig_det_clean_best.pt` | P0 固定；P1 可切换 |
| `DEFAULT_IMGSZ` / `DEFAULT_CONF` / `DEFAULT_IOU` | `640` / `0.35` / `0.70` | 与 CLI 主口径一致；iou 默认值 M3 对照 ultralytics 8.0.200 实测确认 |
| `DEFAULT_VOTE_WINDOW` / `DEFAULT_VOTE_THRESHOLD` | 先对齐磁盘 **4 / 2**（Q1） | 投票滑窗，前端可改 |
| `EVENT_COOLDOWN_SEC` | `10.0` | 事件最小间隔，clamp 5–300 |
| `EVENT_HEARTBEAT_ENABLED` | `True` | 持续报警到点补记 |
| `SNAPSHOT_DIR` | `data/web_events` | 按日期分子目录 |
| `SAMPLE_VIDEO_DIR` | `data/test_videos` | 样例源扫描目录 |
| `UPLOAD_DIR` | `data/web_uploads` | 浏览器上传落盘目录（P0），按日期分子目录、uuid 命名 |
| `ALLOWED_VIDEO_EXTS` | `.mp4,.mov,.avi,.mkv,.m4v,.webm` | 样例/本地/上传统一扩展白名单（实际可解码性以 OpenCV probe/打开为准） |
| `MAX_UPLOAD_MB` | `500` | 上传体积上限，映射 Flask `MAX_CONTENT_LENGTH`；`.env` 可调 |
| `LOCAL_PATH_ALLOWED_ROOTS` | 工程根 + `~/Desktop;~/Downloads;~/Videos`（存在才纳入） | 本机路径直读白名单；`.env` 用 `;`（Windows）追加；设为 `*` 允许任意本机路径（仅回环单机，风险自担，Q7） |
| `CAMERA_DEFAULT_INDEX` | `0` | 摄像头默认设备号 |

### 10.3 标准启动顺序（M5 文档配截图，本节为草案）

1. 启动 Docker Desktop，等待鲸鱼图标稳定；
2. 工程根执行：`docker compose -f deploy/mysql/docker-compose.yml --env-file deploy/mysql/.env up -d`（首次自动初始化 `smoke_detection` 库与 `smoke` 用户）；用 `docker ps`/Workbench 验证 3307 与健康状态；
3. `conda activate dl-gpu`（或直接用绝对路径 python）→ `python run_web.py`；
4. 浏览器打开 `http://127.0.0.1:8000`，`/api/health` 显示 `db_driver=MySQL、db_ok=true`；
5. 实时监控页选择样例视频（或粘贴本机路径 / 上传视频 / 摄像头）→ 调整 conf、投票等参数 → 开始 → 观察画面/状态/ALARM → 违规记录页查看快照与导出；
6. 结束后停止会话；`docker compose ... stop` 可停数据库（数据保留），**不要随意 `down -v`**。

---

## 11. 分期里程碑与验收标准（评审通过后建实施任务）

| 里程碑 | 内容 | 验收标准（可演示/可检查） | 建议工时（供分工参考） |
|---|---|---|---|
| **M1 基础设施** | compose + `.env.example` + 依赖安装 + `run_web.py`/`create_app` 骨架 + `/api/health` + 首页橙色骨架与标签导航 + `.gitignore` | `docker compose up -d` 后容器 healthy、Workbench 可连 3307；`python run_web.py` 启动无报错；浏览器打开首页；health 返回 MySQL 驱动与 `db_ok=true`；`db.create_all` 生成 `detection_event` 表 | 0.5–1 天 |
| **M2 推理管线抽取（Q6）** | 抽 `utils/det_pipeline.py`，CLI 改薄入口并备份；核对 Q1 投票口径 | 原 `infer_det_single.py` 命令行行为/常量/q 退出/统计不变；同一视频回归可出标注帧与 `result_dict`；`process_frame` 可被 Web 导入 | 0.5–1 天 |
| **M3 实时监控 P0（含多源与参数面板，v0.2 扩范围）** | `source_resolver`（样例/本地路径/上传/摄像头）+ 上传与 resolve 接口 + session_manager + MJPEG + 状态轮询 + 参数面板三级生效 + ALARM 横幅 + 资源释放 | ①样例端到端出画；②粘贴工程内与 `Downloads` 视频路径可播放，坏路径/越界给中文报错；③上传 mp4 有进度、落 `data/web_uploads` 且可播放，超限/错格式被拦；④conf/iou/阈值/冷却/开关下一帧生效，投票窗口与 imgsz 应用后状态正确、模型不重载；⑤切源/停止/播放结束后 capture 与线程释放，连续运行 10 分钟无明显内存增长；⑥记录本机 FPS/ms | 1.5–2.5 天（较 v0.1 增加源接入） |
| **M4 事件记录 P0** | recorder 冷却状态机 + 快照 + ORM + 违规记录页（筛选/分页/Modal/标记/删除/CSV） | 仅投票 ALARM 落库；把冷却临时调小（如 2s）验证“开始即记+心跳/关心跳”；任意两条间隔满足配置；删记录联动删图；CSV 用 Excel 打开中文不乱码；MySQL 表记录数与磁盘快照一致；重启 Flask 后历史仍在；`docker restart smoke-mysql` 后数据不丢 | 1 天 |
| **M5 收尾与作业材料** | 重写 README（现有 README 与实际脚本/目录不符）、《部署运行文档》《操作手册》、`schema.sql`、`requirements-web.txt` freeze、样例事件、架构图/ER 图/接口截图、3 分钟演示脚本与**纯录屏兜底**、期末 zip 打包清单 | 按文档在“干净 shell”复制命令可跑；文档含环境版本/启动/停止/备份/常见故障（含上传格式、路径白名单、端口/摄像头占用）；源码、依赖说明、配置文档、模型（weights）、数据集与标注（或下载说明）、系统文档齐全；演示脚本控制在 3 分钟内并彩排 | 1 天 |
| P1（按时间与分工选做） | 语音播报、模型切换（3 个真实权重）、**多文件/目录批量检测**、统计图表、事件短视频片段、上传文件清理与摄像头枚举 | 每项独立验收，不影响 P0 主链路；未完成项从演示与 PPT 中移除，不保留不可用入口 | 机动 |

与现有任务板关系：#14 跟踪本设计；评审通过后新建 M1–M5 实施任务；#8（统一复评 + `experiment_log.csv` 台账）为 M5 模型页与报告提供指标，不阻塞 M1–M4；#9 演示帧标注回流、#11 W_roi、#10 空间融合为数据侧/P2 演进，不进入本期 Web P0。

### 期末提交打包提醒（作业第三条）

- 源码：`webapp/`、`scripts/`、`utils/`、`deploy/`、`run_web.py`、`requirements*.txt`、`.env.example`、`docs/`（排除 `__pycache__`、`.git`、`runs/` 大文件、`data/web_events` 大量运行快照与 `data/web_uploads` 上传视频，仅留 `samples/`）。
- 模型：`weights/` 中实际使用的香烟检测 `.pt`（至少 P0 默认权重；云权重可选），分类/人脸权重按是否在系统使用决定。
- 数据集与标注：`data/somking_det_clean/`（490MB 量级）按作业要求随包或在文档提供下载方式与目录校验（MD5/文件数）；未标注的 `frames_to_label/`、工程外云端上传 zip、`instance/` 应急库、`data/web_uploads/` 不混入提交包。
- 最终压缩包按作业要求命名为 `学号1_学号2_…_组名.zip`；M5 用专门打包清单/脚本核对，避免漏模型、漏文档或把无关大文件打入。

---

## 12. 风险、合规与待确认

### 12.1 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 答辩前 Docker Desktop/MySQL 容器异常 | 系统无法按主路径启动 | 提前一天在答辩机完整启停演练；`/api/health` 明确报错；应急 `SMOKE_DATABASE_URL` 切 SQLite 逃生门（2.4）；**提前录完整系统操作视频嵌入 PPT/本地备用**，3 分钟演示双保险 |
| 教室网络/投影/分辨率不确定 | 前端样式或音频异常 | 全离线 vendor、仅用系统浏览器；投影 F11 彩排；视觉 ALARM 为主、语音为辅；自带笔记本（已确认）与电源/转接头 |
| 模型在监控域仍有误报（如黑色手机） | 违规记录出现误报快照 | 仅投票 ALARM + 10s 冷却 + 违规页“误报”标记；演示选用已验证片段；误报事件导出反哺 #9 数据集，形成“使用→标注→再训练”闭环故事 |
| 上传大文件占盘/超限、封装或编码 OpenCV 打不开 | 上传失败或无法播放 | 流式落盘 + 扩展名/MIME 白名单 + 500MB 上限可配；`resolve-local` probe 与 start 共用打开逻辑并给中文错误；答辩主线固定使用已验证的 H.264 mp4 样例，上传仅作辅助演示 |
| 本机路径直读越界/路径穿越 | 后端被诱导读取允许根外文件 | 仅绑 127.0.0.1；`Path.resolve()` 归一化 + 允许根判定；upload/sample 路径限定各自目录；不提供任意文件下载接口；`*` 放开仅在文档明示风险时由用户主动配置（Q7） |
| OpenCV 双包共存、摄像头占用、端口 3307/8000 冲突 | 启动/取流失败 | M1/M3 记录实测；端口均可在 `.env`/compose 左侧修改；摄像头被占用时给出中文提示；不主动升级 OpenCV 除非出现实际异常 |
| Flask 内置服务器长连接/多标签 | 演示卡顿 | 最新帧缓存 + 单推理线程 + `threaded=True`、关闭 reloader；明确课设单用户定位，不承诺生产并发 |
| 现有 README 与工程现状不符（提到不存在的 `configs/train.py/infer.py`） | 老师按 README 运行失败、扣文档分 | M5 必须重写 README 与部署文档，所有命令在干净 shell 实测后写入 |
| 事件快照/上传视频可能包含现场人像、路径等隐私 | 合规风险 | 系统仅绑定本机、不上传公网；文档注明“仅用于课程设计与授权监控场景，数据采集合法合规、演示数据使用自行录制视频”；提交包默认不含 `web_events` 运行快照与 `web_uploads`，仅留少量自制样例 |

### 12.2 编码前待确认（同 0.2）

1. Q1 投票默认值：先按磁盘 **4/2** 进 M1、页面可调；M2 核对 CLI 历史口径（历史曾用 5/3）。**不阻塞 M1**。
2. Q2 默认样例暂取横屏 `smoke_test2.mp4`（两个视频都进下拉），M3 彩排定稿。**不阻塞 M1**。
3. Q3 是否认可 `webapp/ + deploy/mysql/ + run_web.py`（含 v0.2 的 `source_resolver.py`、`blueprints/sources.py`）目录布局？**M1 落盘前确认**。
4. Q4 是否认可 compose/`.env.example` 的本地课设密码与仅绑定 `127.0.0.1:3307`？**M1 起容器前确认**。
5. Q5 P1 取舍、组员分工（建议：1 人后端+推理引擎/源与会话、1 人原生 JS 前端、1 人事件/数据库+测试、算法/台账/文档由现有主线兼）与答辩倒排日期。
6. Q6 是否同意 M2 对 `infer_det_single.py` 做“抽公共管线、CLI 行为不变”的薄重构（改前备份+回归）。
7. Q7 本机路径直读默认白名单根（工程根 + 桌面/下载/视频）是否认可，还是要求更严格（仅工程根）/更宽松（`*`）？

> 评审方式：可直接在本文档批注或按 Q1–Q7 回复结论；**Q3/Q4 确认后即从 M1（Docker MySQL + Flask 骨架 + health）开始实施**，每完成一个里程碑再进入下一个，不提前实现 P1/P2 空壳功能。

---

## 📌 G. M2 在线推理引擎实测记录（2026-11-24 已交付并验证）

**G.1 交付物（均在 Web 工程根 `smoke-monitor-web\`）**

| 文件 | 职责 |
|---|---|
| `webapp/services/infer_engine.py` | 唯一在线推理实现：`InferParams`（参数校验）、`VoteState`（滑动窗口投票）、`InferEngine`（YOLO 加载 + `process_frame` 检测/橙框 HUD/ALARM 绘制 + JPEG 编码）、`new_vote_state`。不读摄像头/不写文件/不碰数据库，可单测。 |
| `webapp/services/engine_holder.py` | 线程安全引擎单例（同参数命中缓存不重复加载）、`model_brief()`（health 用）、`selftest()`（真实加载+预热）。 |
| `webapp/blueprints/pages.py` | 新增 `POST /api/engine/selftest`；`/api/health` 增加 `model_loaded / model_name / model_device`。 |
| `webapp/templates/index.html` + `static/js/app.js` + `static/css/app.css` | “关于与部署”页新增“模型引擎自检”按钮与结果面板；health 轮询显示模型状态；里程碑路线更新到 M2。 |
| `webapp/config.py` | 新增 `INFER_DEVICE`（auto/0/cpu，默认 auto）。 |
| `scripts/regress_engine.py` | 离线回归脚本：读 `samples/` 视频跑引擎，输出统计摘要 + `runs/engine_check/<ts>/` 抽样标注帧，供与 CLI 目视对照。 |

**G.2 行为口径（与训练 CLI `infer_det_single.py` 对齐，已核对磁盘最新版）**

- 投票默认 **`VOTE_WINDOW=4 / VOTE_THRESHOLD=2`**（Q1 定稿：与磁盘脚本一致；历史 5/3 不再使用）。
- 检测：`model.predict(frame, imgsz, conf, iou, device)`，单类 `cig`；橙框 BGR `(0,165,255)`，标签 `cig {conf:.2f}`。
- 顶部 HUD `[WEB full-frame] FPS | frame N | cig boxes | vote x/4`；`is_alarm` 且画面足够宽时右上红底白字 `SMOKING ALARM`。
- 帧序号从 1 起、推理前取号（已修正初版 frame 0 的偏差）；设备 auto 优先 `cuda:0`，CUDA 不可用回退 CPU；引擎 `process_frame` 内部复制帧再绘制，不污染调用方原帧。
- 输出 JPEG（质量 85），`info` 含 `frame_index / cig_count / max_conf / infer_ms / fps_ema / device / vote_sum / vote_window / is_alarm / boxes`。

**G.3 实测结果**

| 回归 | 权重 / 视频 | 设备 | 帧数 | 平均推理 | 整体 FPS | 备注 |
|---|---|---|---|---|---|---|
| 1 | clean30轮 / smoke_test2.mp4（横屏960×720） | cuda:0 RTX4060 | 372/372 | **12.49 ms** | **53.9** | cig_frames 129、alarm_frames 141；抽帧目视确认 HUD/橙框/ALARM 角标正确 |
| 2 | clean30轮 / smoke_test.mp4（竖屏720×1280） | CPU | 90/421 | **51.66 ms** | **17.1** | 验证 CPU 降级与竖屏尺寸适配，演示优先用 GPU |
| 3 | `POST /api/engine/selftest` | cuda:0 | — | 加载+预热 16.4s（首次含 CUDA 初始化） | — | `code=0`，自检后 health `model_loaded=true / model_device=cuda:0` |

**G.4 验证过程中发现并处理的环境事项（写入 M5 部署文档）**

- 跨天后 **Docker Desktop 引擎可能未启动** → `smoke-mysql` 不会运行、3307 无监听，`/api/health` 返回 503 `db_ok=false`（**这是设计的降级路径，不是 bug**）。处理：启动 Docker Desktop 等引擎就绪；若容器显示 `Exited`（曾被手动 stop，`unless-stopped` 不会自启），执行 `docker start smoke-mysql`。
- 改了后端代码后必须**重启 Web 进程**才生效（`debug=False、use_reloader=False` 不自动重载）；本里程碑曾因旧进程驻留导致新路由 404，重启后正常。M3 起每次验证后按“8010 端口核查 → 停进程”兜底，避免残留。

**G.5 进入 M3 前仍需拍板**

1. **默认权重**：当前 `models/smoke_cig_det_clean_best.pt`（clean 30 轮）；云端 n640/n960 两个 best 已内置。建议 M3 接会话时用 `scripts/regress_engine.py --weights ... --imgsz ...` 对同一视频快速对比后再定 `DEFAULT_WEIGHTS`。
2. **Q8** 单张图片检测是否提前进 P0；**Q5** 组员分工与答辩倒排；**Q2** 默认样例视频 M3 彩排定。
3. M3 范围确认：多源接入（样例下拉 / 本机任意路径 / 浏览器上传 / 摄像头 0）+ 开始前参数面板（运行中锁定）+ MJPEG 实时画面 + 状态轮询 + ALARM 展示 + 切源/停止资源释放。
