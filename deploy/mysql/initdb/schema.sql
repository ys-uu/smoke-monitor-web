-- =====================================================================
-- 抽烟检测监控系统 · 数据库表结构（MySQL 8.0）
-- 说明：
-- 1) 应用默认通过 Flask-SQLAlchemy 的 db.create_all() 自动建表，本文件供查阅与手动部署；
-- 2) 手动部署：在 MySQL 客户端执行本文件；或将本文件挂载到容器
--    /docker-entrypoint-initdb.d/，由容器首次初始化时自动执行；
-- 3) 表结构与 webapp/models.py 的 DetectionEvent 保持一致，字符集 utf8mb4。
-- =====================================================================

CREATE DATABASE IF NOT EXISTS smoke_detection
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE smoke_detection;

CREATE TABLE IF NOT EXISTS detection_event (
  id                INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  event_time        DATETIME(6)  NOT NULL COMMENT '报警记录墙钟时间',
  source_id         VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '来源实例标识 sample:/local:/upload:/camera:',
  source_type       VARCHAR(16)  NOT NULL DEFAULT 'sample' COMMENT '来源类型 sample/local/upload/camera',
  source_name       VARCHAR(255) NOT NULL DEFAULT '' COMMENT '来源展示名',
  frame_index       INT NULL COMMENT '文件源帧号，实时流可空',
  video_time_sec    FLOAT NULL COMMENT '文件源视频内时间（秒）',
  max_conf          FLOAT NULL COMMENT '事件帧最高香烟置信度',
  vote_sum          INT NULL COMMENT '记录时投票票数',
  vote_window       INT NULL COMMENT '投票窗口长度',
  model_name        VARCHAR(128) NOT NULL DEFAULT '' COMMENT '产生事件的权重文件名',
  snapshot_relpath  VARCHAR(512) NOT NULL DEFAULT '' COMMENT '快照相对 data/web_events 的路径',
  bbox_json         TEXT NOT NULL DEFAULT '[]' COMMENT '烟框坐标与置信度 JSON',
  status            VARCHAR(16) NOT NULL DEFAULT 'open' COMMENT '处理状态 open/confirmed/false_alarm',
  reason            VARCHAR(16) NOT NULL DEFAULT 'alarm_start' COMMENT '记录原因 alarm_start/heartbeat',
  note              VARCHAR(255) NULL COMMENT '人工备注/误报原因',
  created_at        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '入库时间',
  KEY idx_event_time (event_time),
  KEY idx_source_time (source_id, event_time),
  KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='违规事件表';
