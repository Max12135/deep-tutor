import httpx
import streamlit as st

def request_backend(api_endpoint, data):
    response = httpx.post(api_endpoint, json=data, timeout=360)
    if response.status_code == 200:
        return response.json()
    else:
        st.write("获取数据失败。状态码：", response.status_code)
