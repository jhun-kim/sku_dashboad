import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 1. 기초 설정
items = [f"수입부품_{chr(65 + i)}" for i in range(10)]  # 수입부품_A ~ J (10종)
start_date = datetime(2025, 1, 1)
data_rows = 10000

# 2. 거래 내역(Transaction) 데이터 생성
transactions = []
for i in range(data_rows):
    item = np.random.choice(items)
    date = start_date + timedelta(days=np.random.randint(0, 350))
    # 입고(Purchase)와 출고(Sale)를 4:6 비율로 생성
    trans_type = np.random.choice(['입고', '출고'], p=[0.4, 0.6])
    qty = np.random.randint(10, 100)

    # 입고 시에만 단가 발생 (5,000원 ~ 15,000원 사이)
    price = np.random.randint(50, 151) * 100 if trans_type == '입고' else 0

    transactions.append([date, item, trans_type, qty, price])

# 데이터프레임 생성 및 날짜 정렬
df_history = pd.DataFrame(transactions, columns=['날짜', '품목명', '구분', '수량', '단가'])
df_history = df_history.sort_values(by=['날짜', '품목명']).reset_index(drop=True)

# 3. 마스터 데이터(재고 분석용) 생성
master_data = []
for item in items:
    # 현재고, 1년 평균 판매량, 3개월 평균 판매량 가상 생성
    stock = np.random.randint(50, 500)
    avg_12m = np.random.randint(100, 300)
    avg_3m = avg_12m + np.random.randint(-50, 100)  # 최근 판매 변동성 부여
    master_data.append([item, stock, avg_12m, avg_3m])

df_master = pd.DataFrame(master_data, columns=['품목명', '현재고', '1년_월평균판매', '3개월_월평균판매'])

# 4. 엑셀 파일로 저장 (2개의 시트)
with pd.ExcelWriter('inventory_test_data.xlsx', engine='openpyxl') as writer:
    df_history.to_excel(writer, sheet_name='거래이력', index=False)
    df_master.to_excel(writer, sheet_name='재고분석기준', index=False)

print("✅ 'inventory_test_data.xlsx' 파일이 성공적으로 생성되었습니다.")