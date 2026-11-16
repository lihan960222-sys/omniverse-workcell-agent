# STEP 与几何检查

几何模块使用 `cadquery-ocp==7.9.3.1.1` 提供的 Open CASCADE API。Windows 和 Linux 使用相同的 STEP 导入、BRep 运算及 Mesh 生成代码。模块需要 `usd-core==25.11` 和项目声明的 Pydantic；在 Isaac Sim 外部的项目 Python 环境执行。

## 文件与坐标

`convert_step(source, output_directory)` 接收 `.stp` 或 `.step` 文件，要求输出目录尚未存在。读取失败、无有效部件或三角化失败时直接报告错误。发生错误后的输出目录可能包含中间文件，重新执行时使用新的输出目录。

输出文件包括：

- `workcell.usda`：装配层级、部件实例及变换；`metersPerUnit=1`，Z 轴向上。
- `geometry.usdc`：从原始 BRep 生成的 Mesh，每个部件定义只保存一次。
- `geometry/*.brep`：用于准确几何计算的部件定义。
- `geometry.json`：源文件哈希、BRep 与 Mesh 哈希、部件路径和单位。

STEPCAFControl_Reader 保留装配定义和实例。多个实例引用同一份 Mesh 和 BRep，实例变换保存在各自的 USD Xform 中。来源名称经过 USD 标识符处理，路径同时包含 XCAF label 标识以区分同名部件。

OCCT 导入时明确设置系统长度为毫米。`.brep` 文件和几何内核计算使用毫米，USD Mesh、公共参数、报告位置与距离使用米，报告体积使用立方米。毫米建模保留了 OCCT 绝对容差在机械零件中的适用尺度。`geometry.json` 分别记录 `length_unit="m"` 和 `brep_length_unit="mm"`。

Mesh 的绝对三角化容差为 `0.0001 m`，角度容差为 `0.2 rad`。Mesh 和 BRep 均来自同一份 OCCT Shape；原始 STEP 保持完整。

## Python 接口

```python
from pathlib import Path
from workcell_agent.geometry import convert_step, check_interference, query_features

converted = convert_step(Path("workcell.stp"), Path("converted"))
manifest = Path(converted["geometry_manifest"])
report = check_interference(manifest)
features = query_features(manifest, "/World/实际部件路径")
```

`convert_step` 返回 `usd_path`、`geometry_manifest` 和 `part_count`。

`check_interference` 参数包括：

| 参数 | 含义 |
|---|---|
| `manifest` | `geometry.json` 路径 |
| `length_tolerance_m` | 接触判定长度容差，默认 `1e-6 m` |
| `volume_tolerance_m3` | 相交判定体积容差，默认 `1e-12 m³` |
| `stage_path` | 可选的当前场景文件，省略时读取导出的 `workcell.usda` |

调用前保存当前场景，或者将当前场景导出为保留部件路径和几何内容的文件，再传入 `stage_path`。检查读取默认时间的世界变换。未保存的 GUI 修改和仿真运行中的内存状态需要由运行服务保存到检查文件。

`query_features(manifest, prim_path, stage_path=None)` 返回指定部件的平面和圆柱面。位置使用世界坐标与米，方向为单位向量；平面包含 `normal`，圆柱面包含 `axis` 和 `radius_m`。特征 `id` 包含 BRep SHA-256 和面编号，只适用于该 BRep 版本。返回 `face_count` 和实际支持的 `features` 列表。

## 静态干涉判定

1. 检查几何文件哈希、Mesh 顶点与拓扑、USD 对象及变换。
2. 根据当前场景中部件的世界变换更新 BRep。
3. 按长度容差扩展包围盒，筛选需要计算的部件对。
4. 使用 `BRepAlgoAPI_Common` 计算共同实体，使用 `BRepGProp.VolumeProperties_s` 计算共同体积。
5. 使用 `BRepExtrema_DistShapeShape` 计算距离和最近点。

共同体积超过体积容差时返回 `interference`；其余结果在距离不超过长度容差时返回 `contact`。小于体积阈值的非零体积仍保存在结果中。`contact` 需要工程规则进一步判断是否允许接触。

结果包含 `findings` 和 `coverage`。每条发现记录部件路径、类别、共同体积、最小距离和最近点。覆盖信息记录部件数、通过包围盒排除的数量、实际进行内核计算的数量，以及缺少 BRep 映射的 USD 几何。存在未映射几何时，`coverage.complete=false`。

报告记录 `kernel_shape_tolerance_m`，取 OCCT 默认建模容差与当前各 BRep 最大拓扑容差中的较大值。请求的长度容差小于该值时拒绝执行。

## 验证与限制

真实测试通过 OCCT 生成 STEP 文件，随后使用正式导入入口执行检查；没有使用 mock。Windows Python 3.11 已验证：

- 毫米装配转换成米制 USD、嵌套层级、共享实例和中文路径。
- 相离、相切、相交、包含、容差内间隙和微小共同体积。
- 包围盒重叠但实体相离时不产生干涉结论。
- 读取修改后的部件位置和父级旋转。
- 平面法向、圆柱轴线及半径。
- BRep 修改、Mesh 修改、未映射几何、开放曲面、非法容差和非均匀缩放。
- 已有输出目录不会被覆盖。

准确体积检查要求有效封闭实体，接受正交变换和正向均匀缩放。几何修改后需要重新转换并建立映射。此接口检查一个静态状态；运行接触检查由 Isaac Sim 模块负责。

尚未在 Linux 或用户的实际 STEP 工站模型上运行本模块。STEP 文件中的轴向约定由导出方决定，本模块保持其坐标数值并标记 Z 轴向上；需要改变工站朝向时调整装配 Xform。

## 依赖依据

- [cadquery-ocp 7.9.3.1.1 发布文件](https://pypi.org/project/cadquery-ocp/7.9.3.1.1/)
- [STEPCAFControl_Reader：装配、名称和颜色导入](https://occt3d.com/dev/doc/refman/html/class_s_t_e_p_c_a_f_control___reader.html)
- [BRepAlgoAPI_Common：共同实体](https://occt3d.com/dev/doc/refman/html/class_b_rep_algo_a_p_i___common.html)
- [BRepGProp：体积属性](https://occt3d.com/dev/doc/refman/html/class_b_rep_g_prop.html)
- [BRepExtrema_DistShapeShape：距离与最近点](https://occt3d.com/dev/doc/refman/html/class_b_rep_extrema___dist_shape_shape.html)
- [BRepAdaptor_Surface：几何面查询](https://occt3d.com/dev/doc/refman/html/class_b_rep_adaptor___surface.html)
- [OCP 许可证说明](https://github.com/CadQuery/OCP#license)

在线 OCCT API 页面当前显示 8.0.1；本模块使用的函数签名另外通过已安装的 OCP 7.9.3.1.1 Python 绑定和真实执行验证。
