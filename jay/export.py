import sqlite3
import pandas as pd

# 1. 기존 내 컴퓨터의 DB 파일 연결
conn = sqlite3.connect('assets.db')

# 2. 데이터 꺼내오기
df = pd.read_sql_query("SELECT * FROM transactions", conn)

# 3. 한글이 깨지지 않도록 안전하게 CSV(엑셀 호환) 파일로 저장
df.to_csv('saved_data.csv', index=False, encoding='utf-8-sig')

print("✅ 성공! saved_data.csv 파일이 생성되었습니다.")