# 抽烟检测监控系统（smoke-monitor-web）

基于 YOLO 的抽烟检测 B/S 监控系统：浏览器前端 + Flask 后端 + YOLO 推理三层结构，支持视频源接入、逐帧检测与多帧投票报警、事件级违规记录、记录查询与 CSV 导出。

## 技术栈

- 前端：原生 HTML / CSS / JavaScript（无 Node 构建链，第三方资源本地化）
- 后端：Flask 3.1 + Flask-SQLAlchemy（ORM）
- 推理：Ultralytics YOLOv8（有 CUDA 用 GPU，无 GPU 自动回退 CPU）
- 数据库：MySQL 8.0（Docker 独立容器，独立数据卷）

## 快速开始（Windows / PowerShell，工程根目录）

前置条件：Python 3.10、Docker Desktop；可选 NVIDIA GPU 与 CUDA 驱动。

1. 准备环境变量（按需修改，`.env` 不提交 git）：

   ```powershell
   Copy-Item deploy/mysql/.env.example deploy/mysql/.env
   ```

2. 启动数据库容器：

   ```powershell
   docker compose -f deploy/mysql/docker-compose.yml --env-file deploy/mysql/.env up -d
   ```

3. 安装 Python 依赖（建议虚拟环境 / conda 环境）：

   ```powershell
   pip install -r requirements-web.txt
   ```

4. 启动应用：

   ```powershell
   python run_web.py
   ```

5. 浏览器访问 <http://127.0.0.1:8010>，先在“关于与部署”页执行模型引擎自检，再进入实时监控。

## 目录结构

```text
smoke-monitor-web/
├─ run_web.py              # 一键启动入口
├─ requirements-web.txt    # Python 依赖版本
├─ webapp/                 # Flask 应用
│  ├─ config.py            # 集中配置（环境变量优先）
│  ├─ models.py            # DetectionEvent ORM
│  ├─ blueprints/          # 路由与 API
│  ├─ services/            # 推理引擎、引擎单例等服务
│  ├─ templates/           # 页面模板
│  └─ static/              # 前端 CSS / JS
├─ deploy/mysql/           # compose、.env 模板、initdb/schema.sql
├─ models/                 # 检测权重（.pt，工程自包含）
├─ samples/                # 样例视频
├─ data/                   # 运行产物：web_events 快照、web_uploads 上传
├─ scripts/                # 离线回归等脚本
└─ docs/                   # 项目文档
```

## 常用命令

```powershell
# 停止数据库但保留数据
docker compose -f deploy/mysql/docker-compose.yml stop
# 查看容器状态
docker ps
# 查看应用日志：直接观察 python run_web.py 的终端输出
```

> 切勿随意执行带 `-v` 的 compose down，会删除命名数据卷导致事件数据丢失。

## 文档索引

- [开发参考文档](docs/开发参考文档.md)：团队开发环境、模块边界、配置项与 API 契约
- [系统设计方案](docs/Web监控系统设计方案.md)：设计决策与实施记录
- [需求分析文档](docs/抽烟检测监控系统需求分析文档.docx)：需求基线（Word）
- [图目录](docs/diagrams/需求分析图.drawio)：用例图与时序图 drawio 源文件

## 常见问题

- **端口被占用 / 启动报端口冲突**：修改 `deploy/mysql/.env` 的 `WEB_PORT` 或 `SMOKE_MYSQL_HOST_PORT` 为空闲端口，注意连接串端口要同步修改。
- **数据库连接失败**：确认 Docker Desktop 已启动、容器处于运行状态（`docker ps`），健康检查会明确返回数据库状态。
- **没有 GPU 或 CUDA 不可用**：推理自动回退 CPU，帧率下降但功能完整；也可用 `SMOKE_INFER_DEVICE=cpu` 显式指定。
- **修改后端代码后页面无变化**：本工程关闭了自动重载，需在终端停止 `python run_web.py` 后重新启动。
