import openslide
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QTimer, QRectF, Signal
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtWidgets import (QMainWindow, QGraphicsView,
                               QGraphicsScene, QGraphicsPixmapItem, QFileDialog, QMessageBox)


class WSIView(QGraphicsView):
    """
    核心视口组件：负责处理鼠标交互（平移、缩放）并按需调度 OpenSlide 渲染
    """
    view_rect_changed = Signal(QRectF)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. 初始化场景 (Scene)
        self.scene_canvas = QGraphicsScene(self)
        self.setScene(self.scene_canvas)

        # 宏观底图铺垫层
        self.bg_layer_item = QGraphicsPixmapItem()
        self.bg_layer_item.setZValue(-1)
        self.scene_canvas.addItem(self.bg_layer_item)

        # 2. 核心渲染载体：整个 Scene 中只保留一个 PixmapItem 用于显示当前视口图像
        # 这样可以绝对避免频繁创建删除 Item 导致的内存泄漏
        self.viewport_item = QGraphicsPixmapItem()
        self.viewport_item.setZValue(0)
        self.scene_canvas.addItem(self.viewport_item)

        # 3. 视图优化设置
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)  # 开启平滑插值，防止缩放时出现马赛克
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 隐藏滚动条，实现类似谷歌地图的纯净画布
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 缩放锚点：以鼠标指针当前位置为中心进行缩放
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        # 4. 后端引擎与状态变量
        self.slide = None
        self._current_qimg = None  # 保持对当前 QImage 的引用，防止被 Python GC 提前回收引发崩溃

        # 交互状态
        self._is_panning = False
        self._last_mouse_pos = None

        # 5. 防抖定时器 (Debounce)
        # 在连续拖拽或滚轮时，不触发耗时的 read_region，动作停止 150ms 后才渲染高清图
        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(150)
        self.render_timer.timeout.connect(self._render_high_res_viewport)

    def load_wsi(self, file_path):
        """加载 SVS 文件并初始化绝对坐标系"""
        try:
            self.slide = openslide.OpenSlide(file_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开文件:\n{e}")
            return

        # 获取 Level 0 的绝对物理尺寸
        w, h = self.slide.dimensions
        # 将 Scene 的尺寸严格设置为 WSI Level 0 的尺寸
        # 建立全局绝对坐标系：Scene 的 (0, 0) 就是切片的左上角
        self.scene_canvas.setSceneRect(0, 0, w, h)

        # 清空视图之前的变换
        self.resetTransform()

        try:
            # 提取倒数第一层（即最低分辨率层，体积最小，加载极快）
            last_level = self.slide.level_count - 1
            dim = self.slide.level_dimensions[last_level]

            # OpenSlide 默认提取为 RGBA 格式，需转为 RGB
            thumb_rgba = self.slide.read_region((0, 0), last_level, dim)
            thumb_img = thumb_rgba.convert("RGB")

            # 设置到底图图层中
            self.bg_layer_item.setPixmap(QPixmap.fromImage(ImageQt(thumb_img)))

            # 【核心映射算式】：Level 0 物理宽度 / 缩略图宽度
            downsample_factor = w / dim[0]

            # 将低分辨率的缩略图强制物理放大 downsample_factor 倍
            # 这样这张图就刚好 1:1 铺满了无穷大的 Scene 画布，充当兜底的障眼法
            self.bg_layer_item.setScale(downsample_factor)

        except Exception as e:
            print(f"宏观底图加载失败（不影响核心功能）:{e}")

        # 计算初始缩放比例（让整个切片刚好适应当前窗口大小）
        view_rect = self.viewport().rect()
        scale_w = view_rect.width() / w
        scale_h = view_rect.height() / h
        initial_scale = min(scale_w, scale_h) * 0.95  # 留 5% 边距

        self.scale(initial_scale, initial_scale)

        # 触发首次渲染
        self._render_high_res_viewport()

    # ==================== 模块 B: 交互事件重写 ====================
    def wheelEvent(self, event):
        """重写滚轮事件：实现基于鼠标锚点的平滑缩放"""
        if not self.slide: return

        # 每次滚动的缩放步长
        zoom_factor = 1.15
        if event.angleDelta().y() < 0:
            zoom_factor = 1.0 / zoom_factor

        # 计算未来的缩放比例
        current_scale = self.transform().m11()
        new_scale = current_scale * zoom_factor

        # 限制缩放范围：最大放大到 Level 0 (1.0)，最小缩小到刚好塞满屏幕
        if new_scale > 1.0:
            zoom_factor = 1.0 / current_scale

        # 执行缩放 (由于设置了 AnchorUnderMouse，Qt 会自动处理偏移数学计算)
        self.scale(zoom_factor, zoom_factor)

        # 重置防抖定时器
        self.render_timer.start()
        self._trigger_view_update()


    def mousePressEvent(self, event):
        """重写鼠标按下：开启平移"""
        if event.button() == Qt.LeftButton and self.slide:
            self._is_panning = True
            self._last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)
        self._trigger_view_update()

    def mouseMoveEvent(self, event):
        """重写鼠标移动：计算偏移量并调整滚动条实现平移"""
        if self._is_panning:
            current_pos = event.position().toPoint()
            delta = current_pos - self._last_mouse_pos
            self._last_mouse_pos = current_pos

            # 通过操作隐藏的滚动条来实现画布平移
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())

            # 平移时重置防抖定时器
            self.render_timer.start()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """重写鼠标释放：结束平移"""
        if event.button() == Qt.LeftButton:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
            self.render_timer.start()
        super().mouseReleaseEvent(event)

    # ==================== 模块 C: 视口按需渲染核心逻辑 ====================
    def _render_high_res_viewport(self):
        """
        核心渲染逻辑：坐标映射 -> 计算层级 -> 截取图像 -> 对齐显示
        """
        if not self.slide: return

        # 1. 视图 -> Scene 坐标映射
        # 获取当前 Viewport 在屏幕上的矩形
        viewport_rect = self.viewport().rect()
        # 将屏幕矩形映射到 Scene 坐标系（即 Level 0 绝对坐标系）中，获取可见的物理区域
        visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()

        # 与 Scene 的物理边界取交集，防止读取超出 WSI 范围的无效数据
        intersected_rect = visible_scene_rect.intersected(self.scene_canvas.sceneRect())
        if intersected_rect.isEmpty():
            return

        # 2. 动态层级 (Level) 计算
        # 当前视图的缩放比例（例如 0.1 表示缩小了 10 倍显示）
        current_scale = self.transform().m11()
        # 目标降采样率 (Downsample) = 1 / 缩放比例。缩小 10 倍，意味着我们需要 downsample 约为 10 的层级
        target_downsample = 1.0 / current_scale

        # 让 OpenSlide 根据目标降采样率，挑选一个最佳的分辨率金字塔层级
        best_level = self.slide.get_best_level_for_downsample(target_downsample)
        level_downsample = self.slide.level_downsamples[best_level]

        # 3. 计算 OpenSlide 读取参数
        # OpenSlide 要求传入 Level 0 坐标系下的 (x, y) 整数起点
        loc_x = int(intersected_rect.left())
        loc_y = int(intersected_rect.top())

        # 截取尺寸 = Level 0 物理尺寸 / 该层级的真实降采样率
        # (确保我们从 OpenSlide 提取出来的像素矩阵大小约等于屏幕显示大小，避免 CPU 提取出过大的矩阵)
        size_w = int(intersected_rect.width() / level_downsample)
        size_h = int(intersected_rect.height() / level_downsample)

        if size_w <= 0 or size_h <= 0: return

        # 4. 从后端读取特定范围图像块 (IO 耗时操作)
        try:
            # 返回的是 PIL Image (RGBA 格式)
            pil_img = self.slide.read_region((loc_x, loc_y), best_level, (size_w, size_h))
        except Exception as e:
            print(f"OpenSlide Read Error: {e}")
            return

        # 5. PIL Image 转 QPixmap (内存操作)
        self._current_qimg = ImageQt(pil_img)  # 转换并保持引用
        pixmap = QPixmap.fromImage(self._current_qimg)

        # 6. 对齐坐标与场景更新
        # 替换旧的显示图像
        self.viewport_item.setPixmap(pixmap)

        # 将图片项的绝对起点放置在 Level 0 坐标系的对应位置
        self.viewport_item.setPos(loc_x, loc_y)

        # 【关键步骤】由于我们提取的是降采样过的图像，为了让它在 Level 0 场景中占据正确的物理大小，
        # 我们必须把这张图片放大 level_downsample 倍！
        # (此时 QGraphicsView 的缩小和这里的放大相互抵消，最终呈现在屏幕上是 1:1 的清晰像素)
        self.viewport_item.setScale(level_downsample)

        # ==================== 模块 D: 鹰眼图 ====================
    def get_visible_rect(self):
        """获取当前主视图处于 Level 0 坐标系下的可见矩形区域"""
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def _trigger_view_update(self):
        """在缩放和滚动后调用此方法发射信号"""
        self.view_rect_changed.emit(self.get_visible_rect())


class MainWindow(QMainWindow):
    """主窗口容器"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("WSI 高性能阅片器基座 (Viewport Rendering)")
        self.resize(1280, 800)

        # 设置中心视图
        self.viewer = WSIView(self)
        self.setCentralWidget(self.viewer)

        # 菜单栏初始化
        self._init_menu()

    def _init_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")

        open_action = file_menu.addAction("打开 WSI 文件...")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择全尺寸病理切片",
            "",
            "WSI Files (*.svs *.tif *.ndpi)"
        )
        if file_path:
            self.viewer.load_wsi(file_path)

# if __name__ == "__main__":
#    app = QApplication(sys.argv)
#    window = MainWindow()
#    window.show()
#    sys.exit(app.exec())