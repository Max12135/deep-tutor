import ast


def convert_knowledge_perspectives_to_markdown(data):
    markdown_text = ""
    for category, items in data.items():
        markdown_text += f"- **{category.capitalize()}**\n"
        for item in items:
            markdown_text += f"  - {item}\n"
    return markdown_text


def prepare_markdown_document(document_structure, knowledge_points, knowledge_drafts):
    if isinstance(knowledge_points, str):
        try:
            knowledge_points = ast.literal_eval(knowledge_points)
        except Exception:
            knowledge_points = []
    if isinstance(knowledge_drafts, str):
        try:
            knowledge_drafts = ast.literal_eval(knowledge_drafts)
        except Exception:
            knowledge_drafts = []
    if isinstance(document_structure, str):
        try:
            document_structure = ast.literal_eval(document_structure)
        except Exception:
            document_structure = {}

    # 确保 document_structure 是字典
    if not isinstance(document_structure, dict):
        document_structure = {}

    # 确保 knowledge_points 和 knowledge_drafts 是列表
    if not isinstance(knowledge_points, list):
        knowledge_points = []
    if not isinstance(knowledge_drafts, list):
        knowledge_drafts = []

    part_titles = {
        'foundational': "## 基础概念",
        'practical': "## 实践应用",
        'strategic': "## 进阶洞察"
    }

    # 安全地获取文档结构字段
    title = document_structure.get('title', '学习文档')
    overview = document_structure.get('overview', '')
    summary = document_structure.get('summary', '')

    learning_document = f"# {title}"
    if overview:
        learning_document += f"\n\n{overview}"

    for k_type, part_title in part_titles.items():
        learning_document += f"\n\n{part_title}\n"
        for k_id, knowledge_point in enumerate(knowledge_points):
            if knowledge_point.get('type') != k_type:
                continue
            if k_id >= len(knowledge_drafts):
                continue
            knowledge_draft = knowledge_drafts[k_id]
            kd_title = knowledge_draft.get('title', '知识点')
            kd_content = knowledge_draft.get('content', '')
            learning_document += f"\n\n### {kd_title}\n"
            if kd_content:
                learning_document += f"\n\n{kd_content}\n"

    if summary:
        learning_document += f"\n\n## 总结\n\n{summary}"

    return learning_document
