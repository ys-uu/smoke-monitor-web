# -*- coding: utf-8 -*-
"""两阶段推理离线回归，用 samples/ 样例视频验证检测、投票和绘制。

用法（在 Web 工程根 smoke-monitor-web，dl-gpu 环境）：
    python scripts/regress_engine.py                       # 默认权重 + smoke_test2.mp4
    python scripts/regress_engine.py --video samples/smoke_test.mp4
    python scripts/regress_engine.py --weights models/smoke_cig_clean_n960_e100_best.pt --imgsz 960
    python scripts/regress_engine.py --device cpu --max-frames 60

输出：控制台统计摘要 + runs/engine_check/<时间戳>/ 下抽样标注帧（供与 CLI 出片目视对照）。
不修改训练基地任何文件；不启动 Flask、不写数据库。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

PROJ_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ_ROOT))  # 允许直接 python scripts/xxx.py 运行时 import webapp

from webapp.services.infer_engine import InferEngine, InferParams, new_vote_state  # noqa: E402
from webapp.config import Config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="人脸与香烟两阶段推理的离线回归")
    ap.add_argument("--video", default="samples/smoke_test2.mp4", help="样例视频（相对 Web 工程根）")
    ap.add_argument("--weights", default=Config.DEFAULT_WEIGHTS)
    ap.add_argument("--face-weights", default=Config.DEFAULT_FACE_WEIGHTS)
    ap.add_argument("--face-conf", type=float, default=Config.DEFAULT_FACE_CONF)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--imgsz", type=int, default=Config.DEFAULT_IMGSZ)
    ap.add_argument("--conf", type=float, default=Config.DEFAULT_CONF)
    ap.add_argument("--iou", type=float, default=Config.DEFAULT_IOU)
    ap.add_argument("--use-vote", action="store_true", default=Config.DEFAULT_USE_VOTE)
    ap.add_argument("--vote-window", type=int, default=Config.DEFAULT_VOTE_WINDOW)
    ap.add_argument("--vote-threshold", type=int, default=Config.DEFAULT_VOTE_THRESHOLD)
    ap.add_argument("--max-frames", type=int, default=0, help="0=整段；>0 只跑前 N 帧")
    ap.add_argument("--sample-every", type=int, default=60, help="每 N 帧保存一张标注帧")
    args = ap.parse_args()

    video = PROJ_ROOT / args.video
    weights = PROJ_ROOT / args.weights
    face_weights = PROJ_ROOT / args.face_weights
    if not video.is_file():
        print(f"[错误] 视频不存在: {video}")
        return 1
    if not weights.is_file():
        print(f"[错误] 权重不存在: {weights}")
        return 1
    if not face_weights.is_file():
        print(f"[错误] 人脸权重不存在: {face_weights}")
        return 1

    params = InferParams(
        weights_path=str(weights), device=args.device, imgsz=args.imgsz,
        conf=args.conf, iou=args.iou, use_vote=args.use_vote,
        vote_window=args.vote_window, vote_threshold=args.vote_threshold,
        face_weights_path=str(face_weights), face_conf=args.face_conf,
    )
    print(f"[加载] {face_weights.name} → {weights.name} | device={args.device} imgsz={args.imgsz} conf={args.conf}")
    t_load = time.time()
    engine = InferEngine(params)
    print(f"[就绪] 设备={engine.device_desc} 加载+预热 {time.time()-t_load:.2f}s")

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"[错误] 无法打开视频: {video}")
        return 1
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    out_dir = PROJ_ROOT / "runs" / "engine_check" / time.strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    state = new_vote_state(params)
    frames = 0
    face_frames = 0
    cig_frames = 0
    alarm_frames = 0
    total_boxes = 0
    infer_ms_sum = 0.0
    wall_start = time.time()
    limit = args.max_frames if args.max_frames > 0 else total

    while frames < limit:
        ret, frame = cap.read()
        if not ret:
            break
        jpeg, info = engine.process_frame(frame, state)
        frames += 1
        if info["face_count"] > 0:
            face_frames += 1
        if info["cig_count"] > 0:
            cig_frames += 1
        if info["is_alarm"]:
            alarm_frames += 1
        total_boxes += info["cig_count"]
        infer_ms_sum += info["infer_ms"]

        # 抽样保存标注帧 + 每个 ALARM 触发点保存一张（目视对照用）
        if frames % args.sample_every == 0 or (info["is_alarm"] and alarm_frames == 1):
            (out_dir / f"f{frames:04d}_alarm{int(info['is_alarm'])}_v{info['vote_sum']}.jpg").write_bytes(jpeg)
        if frames % 100 == 0:
            print(f"  ... 帧 {frames}/{limit} | 人脸 {info['face_count']} | 香烟 {info['cig_count']} "
                  f"| vote {info['vote_sum']}/{info['vote_window']} | {info['infer_ms']:.1f}ms")

    cap.release()
    wall = time.time() - wall_start
    summary = {
        "weights": weights.name,
        "face_weights": face_weights.name,
        "face_conf": args.face_conf,
        "video": video.name,
        "device": engine.device_desc,
        "imgsz": args.imgsz,
        "conf": args.conf,
        "iou": args.iou,
        "vote": f"{args.vote_threshold}/{args.vote_window}" if args.use_vote else "off",
        "frames": frames,
        "video_total_frames": total,
        "src_fps": round(src_fps, 2),
        "face_frames": face_frames,
        "cig_frames": cig_frames,
        "cig_frame_ratio": round(cig_frames / max(1, frames), 4),
        "alarm_frames": alarm_frames,
        "alarm_frame_ratio": round(alarm_frames / max(1, frames), 4),
        "total_boxes": total_boxes,
        "avg_infer_ms": round(infer_ms_sum / max(1, frames), 2),
        "wall_fps": round(frames / max(1e-6, wall), 2),
        "out_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("两阶段推理回归摘要")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("=" * 60)
    print(f"抽样标注帧目录: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
