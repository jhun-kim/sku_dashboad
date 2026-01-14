from datetime import datetime
import pandas as pd

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
