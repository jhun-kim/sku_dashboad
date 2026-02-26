from datetime import datetime
import pandas as pd

def test():
    file_path = 'inventory_10k_data.xlsx'
    df_history = pd.read_excel(file_path)

    df_history['datetime'] = df_history['날짜'].apply(lambda x: str(x).split(' ')[0])
    df_history['datetime'] = df_history['datetime'].apply(lambda x: datetime.strptime(str(x), "%Y-%m-%d"))

    df_history['날짜'] = df_history['datetime']

    # 2. '구분'이 '입고'인 데이터만 필터링
    # df_1 = df_history[df_history['구분'] == '입고'].copy()
    # df_2 = df_history[df_history['구분'] != '입고'].copy()


    # 3. 가중치를 위한 총 금액(수량 * 단가) 컬럼 생성
    df_history['총금액'] = df_history['수량'] * df_history['단가']

    # 4. 날짜, 품목명별로 그룹화하여 수량과 총금액 합산
    grouped = df_history.groupby(['날짜', '품목명', '구분']).agg({
        '수량': 'sum',
        '총금액': 'sum'
    }).reset_index()

    # 5. 최종 단가 계산 (모든 합계 금액 / 모든 수량 합계)
    grouped['평균단가'] = grouped['총금액'] / grouped['수량']
    grouped['단가'] = grouped['평균단가']
    # 결과 출력
    print(grouped[['날짜', '품목명', '구분', '수량', '평균단가']])

    # df_3 = pd.concat(df_1, df_2).reset_index(drop=True)
    df_history = df_history.sort_values(['날짜'], ascending=True).reset_index(drop=True)

    df_history.to_excel('inventory_data.xlsx', index=False)


import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 1. 기초 설정
items = [f"수입물품_{chr(65 + i)}" for i in range(10)]
start_date = datetime(2025, 1, 1)
data_rows = 100

# 2. 거래 내역 생성 (로직 반영)
transactions = []
for i in range(data_rows):
    item = np.random.choice(items)
    date = start_date + timedelta(days=np.random.randint(0, 350))

    # [수정] 대분류(구분) 결정
    trans_type = np.random.choice(['입고', '출고'], p=[0.4, 0.6])

    # [수정] 대분류에 따른 소분류(세부구분) 매칭
    if trans_type == '입고':
        sub_type = np.random.choice(['매입', '반품'], p=[0.8, 0.2])  # 매입이 더 많게 설정
        price = np.random.randint(50, 151) * 100
    else:
        sub_type = np.random.choice(['매출', '샘플'], p=[0.9, 0.1])  # 매출이 더 많게 설정
        price = 0

    qty = np.random.randint(10, 100)
    transactions.append([date, item, trans_type, sub_type, qty, price])

# 데이터프레임 생성
df_history = pd.DataFrame(transactions, columns=['날짜', '품목명', '구분', '세부구분', '수량', '단가'])
df_history = df_history.sort_values(by=['날짜', '품목명']).reset_index(drop=True)

# 3. 마스터 데이터 생성 (동일)
master_data = [[item, np.random.randint(50, 500), np.random.randint(100, 300), np.random.randint(50, 400)] for item in
               items]
df_master = pd.DataFrame(master_data, columns=['품목명', '현재고', '1년_월평균판매', '3개월_월평균판매'])

# 4. 저장
with pd.ExcelWriter('inventory_test_data.xlsx', engine='openpyxl') as writer:
    df_history.to_excel(writer, sheet_name='거래이력', index=False)
    df_master.to_excel(writer, sheet_name='재고분석기준', index=False)

print("✅ 로직이 반영된 'inventory_test_data.xlsx' 파일이 생성되었습니다.")