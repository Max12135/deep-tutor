backend_endpoint = "http://127.0.0.1:5000/"
use_mock_data = False
use_search = True

# API 配置
# 注意：httpx 的 timeout 单位是秒（此前误写成 5000，被当成 5000 秒 ≈ 83 分钟）
api_timeout = 300  # 默认超时 300 秒（适配 deepseek-reasoner 慢生成）
