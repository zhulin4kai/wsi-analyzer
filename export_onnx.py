#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WSIAnalyzer — YOLO .pt → .onnx 导出工具
=========================================
用法示例：
    # 使用默认模型（项目根目录下的 yolo26m-outtime.pt）
    python export_onnx.py

    # 指定模型文件与输入尺寸
    python export_onnx.py yolo26m-outtime.pt --imgsz 512

    # 禁用 onnx-simplifier 优化（简化器报错时可尝试）
    python export_onnx.py yolo26m-outtime.pt --no-simplify

导出完成后，将 WSIAnalyzer 中的模型路径指向生成的 .onnx 文件即可。
打包发布时可彻底移除 torch / ultralytics 依赖，只保留 onnxruntime。
"""

import argparse
import sys
from pathlib import Path


def _check_deps():
    """检查导出所需的依赖库是否已安装。"""
    missing = []
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        missing.append("ultralytics")
    try:
        import onnx  # noqa: F401
    except ImportError:
        missing.append("onnx")

    if missing:
        print(
            f"[错误] 缺少以下依赖，请先安装后再运行：\n"
            f"    pip install {' '.join(missing)}\n"
            f"注意：这些依赖仅用于 **导出阶段**，打包发布时不需要。"
        )
        sys.exit(1)


def export(
    pt_path: str,
    imgsz: int = 512,
    opset: int = 17,
    simplify: bool = True,
    output_path=None,
) -> str:
    """
    将 YOLO .pt 权重导出为 ONNX 格式。

    :param pt_path:     输入的 .pt 模型路径
    :param imgsz:       模型输入尺寸（正方形边长，应与训练时的 imgsz 一致）
    :param opset:       ONNX opset 版本（推荐 17，兼容 onnxruntime >= 1.16）
    :param simplify:    是否启用 onnx-simplifier 对计算图进行常量折叠优化
    :param output_path: 可选的输出路径；默认与 .pt 文件同目录，后缀改为 .onnx
    :return:            导出完成的 .onnx 文件绝对路径
    """
    from ultralytics import YOLO  # type: ignore[import-untyped]

    pt_file = Path(pt_path).resolve()
    if not pt_file.exists():
        print(f"[错误] 找不到模型文件：{pt_file}")
        sys.exit(1)

    print(f"[1/3] 正在加载 YOLO 模型：{pt_file}")
    model = YOLO(str(pt_file))

    # 打印模型基本信息
    try:
        model_args = model.model.args
        train_imgsz = model_args.get("imgsz", "未知")
        nc = model_args.get("nc", "未知")
        print(f"      训练 imgsz={train_imgsz}  类别数 nc={nc}")
        if isinstance(train_imgsz, int) and train_imgsz != imgsz:
            print(
                f"[警告] 导出 imgsz ({imgsz}) 与训练 imgsz ({train_imgsz}) 不一致，"
                f"建议使用 --imgsz {train_imgsz}"
            )
    except Exception:
        pass  # 元数据读取失败不影响导出

    print(
        f"[2/3] 正在导出 ONNX"
        f"（imgsz={imgsz}, opset={opset}, simplify={simplify}, nms=False）..."
    )

    # nms=False：不将 NMS 烘焙进 ONNX 计算图。
    # WSIAnalyzer 的 ai_engine 会在全片推理完成后统一执行跨图块的全局 NMS，
    # 若将 NMS 烘焙进图，单图块输出格式会改变，需要额外的后处理适配。
    exported = model.export(
        format="onnx",
        imgsz=imgsz,
        opset=opset,
        simplify=simplify,
        dynamic=False,  # 固定 batch 维度，与 ONNXObjectDetectionAdapter 的批处理逻辑匹配
        half=False,  # float32，确保在无 GPU 的机器上也能正常运行
        nms=False,
        verbose=False,
    )

    default_onnx = Path(str(exported)).resolve()

    # 如果用户指定了输出路径，则移动/重命名
    if output_path:
        dest = Path(output_path).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        default_onnx.rename(dest)
        onnx_path = dest
    else:
        onnx_path = default_onnx

    print(f"[3/3] 正在验证导出结果...")
    _verify(onnx_path, imgsz)

    size_mb = onnx_path.stat().st_size / 1024 / 1024
    print(
        f"\n{'=' * 55}\n"
        f"  导出成功！\n"
        f"  路径：{onnx_path}\n"
        f"  大小：{size_mb:.1f} MB\n"
        f"{'=' * 55}\n"
        f"下一步：\n"
        f"  1. 在 WSIAnalyzer 中选择此 .onnx 文件作为模型权重\n"
        f"  2. 打包前可执行：pip uninstall torch torchvision ultralytics -y\n"
        f"     （保留 onnxruntime 即可，大幅缩减发布包体积）\n"
    )
    return str(onnx_path)


def _verify(onnx_path: Path, imgsz: int):
    """用随机张量对导出的 ONNX 模型执行一次前向推理，验证基本正确性。"""
    try:
        import numpy as np
        import onnxruntime as ort

        session = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
        inp = session.get_inputs()[0]
        # 使用 batch=1 的随机输入
        dummy = np.random.rand(1, 3, imgsz, imgsz).astype(np.float32)
        outputs = session.run(None, {inp.name: dummy})

        out_shape = outputs[0].shape
        print(f"      验证通过 ✓  输入: {list(inp.shape)}  输出: {list(out_shape)}")

        # 给出输出维度说明，帮助确认格式
        if len(out_shape) == 3:
            b, a, c = out_shape
            if a < c:
                # (batch, 4+classes, anchors) — YOLOv8 标准格式
                num_classes = a - 4
                num_anchors = c
            else:
                # (batch, anchors, 4+classes) — 已转置格式
                num_anchors = a
                num_classes = c - 4
            print(
                f"      输出解读：batch={b}, anchors={num_anchors}, "
                f"classes={num_classes}（含 4 个 bbox 坐标）"
            )
    except ImportError:
        print("      [跳过验证] 未安装 onnxruntime，可执行：pip install onnxruntime")
    except Exception as e:
        print(f"      [警告] 验证时遇到异常（不影响导出文件）：{e}")


def main():
    parser = argparse.ArgumentParser(
        description="WSIAnalyzer — YOLO .pt 转 .onnx 导出工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python export_onnx.py\n"
            "  python export_onnx.py yolo26m-outtime.pt --imgsz 640\n"
            "  python export_onnx.py my_model.pt --imgsz 512 --output dist/model.onnx\n"
            "  python export_onnx.py my_model.pt --no-simplify\n"
        ),
    )
    parser.add_argument(
        "pt_path",
        nargs="?",
        default="yolo26m-outtime.pt",
        help="输入的 .pt 模型文件路径（默认：yolo26m-outtime.pt）",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=512,
        help="模型输入图像尺寸，正方形边长（默认：512，应与训练时一致）",
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=17,
        help="ONNX opset 版本（默认：17，需要 onnxruntime >= 1.16）",
    )
    parser.add_argument(
        "--no-simplify",
        action="store_false",
        dest="simplify",
        help="禁用 onnx-simplifier 优化（简化器报错时可尝试此选项）",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="指定输出的 .onnx 文件路径（默认：与 .pt 同目录，后缀改为 .onnx）",
    )

    args = parser.parse_args()

    _check_deps()
    export(args.pt_path, args.imgsz, args.opset, args.simplify, args.output)


if __name__ == "__main__":
    main()
