@echo off
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
streamlit run mx_installments_page0_app_v5_fixed.py
pause
