import re
import os
import json
import pdfplumber
from pypinyin import lazy_pinyin

def extract_text_from_pdf(file_path):
    assert file_path.endswith('.pdf'), "Invalid file format. Please provide a PDF file."
    with pdfplumber.open(file_path) as pdf:
        text = ""
        for page in pdf.pages:
            page_text = page.extract_text()
            text += page_text or ""
        return text

def save_json(file_path, data):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_json(file_path):
    assert os.path.exists(file_path), "File not found."
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data

def sanitize_collection_name(name):
    contains_chinese = bool(re.search(r'[\u4e00-\u9fff]', name))
    if contains_chinese:
        name = ''.join(lazy_pinyin(name))
    else:
        name = name


    sanitized_name = re.sub(r'[^A-Za-z0-9-_]', '_', name)
    sanitized_name = sanitized_name[:63]
    sanitized_name = sanitized_name.strip('_')
    if not sanitized_name[0].isalnum():
        sanitized_name = 'A' + sanitized_name[1:]
    if not sanitized_name[-1].isalnum():
        sanitized_name = sanitized_name[:-1] + 'Z'
    return sanitized_name
