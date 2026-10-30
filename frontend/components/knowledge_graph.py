"""
知识图谱可视化组件

生成美观的线状学习进度知识串，支持：
- 水平线性布局（像一条"知识串"，学完就点亮）
- 节点状态：未学习（浅描边）/ 学习中（砖橙闪烁）/ 已完成（墨色实底）
- 响应式布局：节点过多时自动换行（多行串联）
- 悬浮 tooltip 显示完整名称
- 动态连线颜色随进度变化
"""

import streamlit as st
import streamlit.components.v1 as components
import json


def render_knowledge_graph(
    graph_data: dict,
    current_node_id: str = None,
    height: int = 300,
    on_node_click: callable = None
):
    """渲染知识串图谱

    Args:
        graph_data: 图谱数据 {nodes, edges, layout}
        current_node_id: 当前正在学习的节点ID
        height: 图谱高度（会自动根据节点数调整）
        on_node_click: 节点点击回调（Streamlit 限制，目前仅用于视觉展示）
    """
    nodes = graph_data.get("nodes", [])
    # 根据节点数量自动调整高度
    nodes_per_row = max(1, min(len(nodes), 6))
    rows = max(1, (len(nodes) + nodes_per_row - 1) // nodes_per_row)
    auto_height = max(height, rows * 120 + 60)

    html_code = _generate_graph_html(graph_data, current_node_id, auto_height)
    components.html(html_code, height=auto_height, scrolling=False)


def _generate_graph_html(graph_data: dict, current_node_id: str, height: int) -> str:
    """生成知识串图谱的 HTML 代码"""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if not nodes:
        return "<html><body style='background:#FAF7F2;color:#6E675E;padding:20px;font-family:sans-serif;'>暂无知识点数据</body></html>"

    # 计算布局：每行最多 6 个节点
    nodes_per_row = min(len(nodes), 6)
    total_rows = max(1, (len(nodes) + nodes_per_row - 1) // nodes_per_row)

    # 为每个节点计算位置（百分比）
    node_positions = {}
    for i, node in enumerate(nodes):
        row = i // nodes_per_row
        col = i % nodes_per_row
        # 当前行实际节点数（最后一行可能不满）
        row_start = row * nodes_per_row
        row_end = min(row_start + nodes_per_row, len(nodes))
        row_count = row_end - row_start

        x_pct = (col + 0.5) / row_count * 100
        y_pct = (row + 0.5) / total_rows * 100
        node_positions[node["id"]] = (x_pct, y_pct)

    # 生成节点 HTML 和 CSS
    node_items = []
    for node in nodes:
        node_id = node["id"]
        node_name = node.get("name", "知识点")
        status = node.get("status", "unlearned")
        is_current = (node_id == current_node_id)

        x_pct, y_pct = node_positions.get(node_id, (50, 50))

        # 状态样式（暖纸主题：墨色=已完成，砖橙=学习中）
        if status == "completed":
            bg = "#201D1A"
            border = "#201D1A"
            shadow = "0 2px 8px rgba(90,70,50,0.25)"
            icon = "✓"
            text_color = "#ffffff"
            anim = ""
        elif status == "in_progress" or is_current:
            bg = "#ffffff"
            border = "#C05A3C"
            shadow = "0 0 0 4px rgba(192,90,60,0.12)"
            icon = "▶"
            text_color = "#C05A3C"
            anim = "animation: pulse-accent 1.6s infinite;"
        else:
            bg = "#ffffff"
            border = "#EAE3D8"
            shadow = "none"
            icon = "○"
            text_color = "#A39A8E"
            anim = ""

        # 截断长名称用于显示，tooltip 显示完整
        display_name = node_name[:10] + "…" if len(node_name) > 10 else node_name

        node_items.append({
            "id": node_id,
            "name": node_name,
            "display_name": display_name,
            "icon": icon,
            "x": x_pct,
            "y": y_pct,
            "bg": bg,
            "border": border,
            "shadow": shadow,
            "text_color": text_color,
            "anim": anim,
            "status": status,
        })

    # 生成 SVG 连线
    edge_svgs = []
    node_pos_map = {n["id"]: (n["x"], n["y"]) for n in node_items}
    node_status_map = {n["id"]: n["status"] for n in node_items}

    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src not in node_pos_map or tgt not in node_pos_map:
            continue
        sx, sy = node_pos_map[src]
        tx, ty = node_pos_map[tgt]
        src_status = node_status_map.get(src, "unlearned")
        tgt_status = node_status_map.get(tgt, "unlearned")

        if src_status == "completed" and tgt_status == "completed":
            line_color = "#201D1A"
            opacity = "0.9"
            stroke_width = "3"
        elif src_status == "completed":
            line_color = "#6E675E"
            opacity = "0.7"
            stroke_width = "2.5"
        else:
            line_color = "#EAE3D8"
            opacity = "0.7"
            stroke_width = "2"

        # 计算贝塞尔曲线控制点（轻微弯曲）
        mx = (sx + tx) / 2
        my = (sy + ty) / 2 - 3

        edge_svgs.append(f"""
  <path d="M {sx:.1f} {sy:.1f} Q {mx:.1f} {my:.1f} {tx:.1f} {ty:.1f}"
        stroke="{line_color}" stroke-width="{stroke_width}" fill="none"
        stroke-linecap="round" opacity="{opacity}"/>
  <circle r="3" fill="{line_color}" opacity="{opacity}">
      <animateMotion dur="2.5s" repeatCount="indefinite"
                     path="M {sx:.1f} {sy:.1f} Q {mx:.1f} {my:.1f} {tx:.1f} {ty:.1f}"/>
  </circle>""")

    # 生成节点 HTML
    node_htmls = []
    for n in node_items:
        node_htmls.append(f"""
    <div class="kn-node" data-id="{n['id']}"
         style="left:{n['x']:.1f}%;top:{n['y']:.1f}%;background:{n['bg']};
                border-color:{n['border']};box-shadow:{n['shadow']};
                color:{n['text_color']};{n['anim']}"
         title="{n['name']}">
      <span class="kn-icon">{n['icon']}</span>
      <span class="kn-label">{n['display_name']}</span>
    </div>""")

    nodes_json = json.dumps([{"id": n["id"], "status": n["status"]} for n in node_items], ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: 'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif;
    background: #FAF7F2;
    height: {height}px; overflow: hidden;
  }}
  .kn-container {{
    position: relative; width: 100%; height: {height}px;
  }}
  .kn-edges {{
    position: absolute; top:0; left:0; width:100%; height:100%;
    pointer-events: none;
  }}
  .kn-node {{
    position: absolute;
    transform: translate(-50%, -50%);
    padding: 7px 14px;
    border-radius: 999px;
    border: 2.5px solid;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 5px;
    z-index: 10;
    transition: transform 0.25s ease, box-shadow 0.25s ease;
    white-space: nowrap;
    max-width: 160px;
  }}
  .kn-node:hover {{
    transform: translate(-50%, -50%) scale(1.12) !important;
    filter: brightness(1.05);
    z-index: 20;
  }}
  .kn-icon {{ font-size: 13px; flex-shrink: 0; }}
  .kn-label {{
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 110px;
  }}
  @keyframes pulse-accent {{
    0%,100% {{ box-shadow: 0 0 0 4px rgba(192,90,60,0.12); }}
    50% {{ box-shadow: 0 0 0 7px rgba(192,90,60,0.06); }}
  }}
  .kn-legend {{
    position: absolute; bottom: 8px; right: 10px;
    display: flex; gap: 12px; font-size: 11px;
    color: #6E675E; background: rgba(250,247,242,0.92);
    padding: 6px 12px; border-radius: 8px;
    backdrop-filter: blur(4px);
    border: 1px solid rgba(90,70,50,0.10);
  }}
  .kn-legend-item {{ display: flex; align-items: center; gap: 5px; }}
  .kn-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .kn-dot.done {{ background: #201D1A; }}
  .kn-dot.prog {{ background: #ffffff; border: 2px solid #C05A3C; width: 8px; height: 8px; }}
  .kn-dot.wait {{ background: #ffffff; border: 2px solid #EAE3D8; width: 8px; height: 8px; }}
</style>
</head>
<body>
<div class="kn-container">
  <svg class="kn-edges" viewBox="0 0 100 100" preserveAspectRatio="none">
    {"".join(edge_svgs)}
  </svg>
  {"".join(node_htmls)}
  <div class="kn-legend">
    <div class="kn-legend-item"><div class="kn-dot done"></div><span>已完成</span></div>
    <div class="kn-legend-item"><div class="kn-dot prog"></div><span>学习中</span></div>
    <div class="kn-legend-item"><div class="kn-dot wait"></div><span>未开始</span></div>
  </div>
</div>
<script>
  // 添加错误处理，避免 Streamlit 重新渲染时出现 removeChild 错误
  window.onerror = function(msg, url, line, col, error) {{
    if (msg.indexOf('removeChild') !== -1) {{
      console.log('DOM update ignored');
      return true;
    }}
    return false;
  }};
  
  // 使用 MutationObserver 监听 DOM 变化，避免冲突
  try {{
    document.querySelectorAll('.kn-node').forEach(function(node) {{
      if (!node.hasAttribute('data-listener-attached')) {{
        node.setAttribute('data-listener-attached', 'true');
        node.addEventListener('click', function() {{
          window.parent.postMessage({{type:'node_click', nodeId: this.getAttribute('data-id')}}, '*');
        }});
      }}
    }});
  }} catch(e) {{
    console.log('Node listener attachment skipped');
  }}
</script>
</body>
</html>"""
    return html


def create_simple_linear_graph(knowledge_points: list) -> dict:
    """创建简单的线性知识图谱（无需 LLM）

    Args:
        knowledge_points: 知识点列表

    Returns:
        Dict containing graph data
    """
    nodes = []
    edges = []
    total = len(knowledge_points)

    for i, kp in enumerate(knowledge_points):
        name = kp.get("name", f"知识点{i+1}")
        # 生成稳定唯一 ID
        node_id = (
            name.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("(", "")
            .replace(")", "")
            .replace("/", "_")
            .replace(".", "_")
            [:40]  # 限长
        )
        # 若 ID 冲突则加序号
        existing_ids = [n["id"] for n in nodes]
        if node_id in existing_ids:
            node_id = f"{node_id}_{i}"

        # 水平线性布局（位置由渲染层重新计算，此处仅占位）
        nodes.append({
            "id": node_id,
            "name": name,
            "type": kp.get("type", "foundational"),
            "description": kp.get("description", name),
            "level": 1,
            "position_x": (i + 1) / (total + 1) if total > 0 else 0.5,
            "position_y": 0.5,
            "status": "unlearned"
        })

        if i > 0:
            edges.append({
                "source": nodes[i - 1]["id"],
                "target": node_id,
                "type": "sequence",
                "label": "next"
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "layout": {
            "type": "linear",
            "direction": "horizontal"
        }
    }
